__all__=["PrepareNodeParserJSON", "PrepareNodeParserXML", "PrepareNode"]

import sys, string, time, os, xml.dom.minidom, threading, traceback, re, random, yaml, uuid, copy, json
import xenrt
import pprint

class PrepareNodeParserBase(object):
    def __init__(self, parent, data):
        self.data = data
        self.parent = parent

    def expand(self, s):
        return xenrt.seq.expand(s, self.parent.params)

class PrepareNodeParserJSON(PrepareNodeParserBase):
    def parse(self):
        for x in self.data.get("pools", []):
            self.handlePoolNode(x)
        for x in self.data.get("hosts", []):
            self.handleHostNode(x)
        for x in self.data.get("utilityvms", []):
            self.handleUtilityVMNode(x)
        for x in self.data.get("templates", []):
            self.handleInstanceNode(x, template=True)
        for x in self.data.get("instances", []):
            self.handleInstanceNode(x, template=False)
        for x in self.data.get("vlans", []):
            self.handleVLANNode(x)
        for x in self.data.get("blueprints", []):
            self.handleBlueprintNode(x)
        
        if "multihosts" in self.data:
            self.handleMultiHostNode(self.data['multihosts'])

        if "cloud" in self.data:
            self.handleCloudNode(self.data['cloud'])


    def __minAvailable(self, allocated):
        i = 0
        while True:
            if i not in allocated:
                return i
            i += 1

    def __minAvailableHost(self, additionalHosts=[]):
        hosts = [int(x['id']) for x in self.parent.hosts]
        hosts.extend(additionalHosts)
        return self.__minAvailable(hosts)

    def __minAvailablePool(self):
        return self.__minAvailable([int(x['id']) for x in self.parent.pools])

    def handleNetworkNode(self, node):
        doc = xml.dom.minidom.Document()
        netNode = doc.createElement("NETWORK")
        if "controller" in node:
            netNode.setAttribute("controller", node['controller'])
        for n in node.get("physical_networks", []):
            physnode = doc.createElement("PHYSICAL")
            if "network" in n:
                physnode.setAttribute("network", n['network'])
            if "bond_mode" in n:
                physnode.setAttribute("bond-mode", n['bond_mode'])
            if "jumbo" in n:
                physnode.setAttribute("jumbo", "yes" if n['jumbo'] else "no")
            if "speed" in n:
                physnode.setAttribute("speed", n['speed'])
            if "name" in n:
                physnode.setAttribute("name", n['name'])
            if "specified_nics" in n:
                for x in n['specified_nics']:
                    nicnode = doc.createElement("NIC")
                    nicnode.setAttribute("enum", x)
                    physnode.appendChild(nicnode)
            elif "nics" in n:
                for x in range(n['nics']):
                    nicnode = doc.createElement("NIC")
                    physnode.appendChild(nicnode)
            else:
                nicnode = doc.createElement("NIC")
                physnode.appendChild(nicnode)
            if n.get("management"):
                mgmtnode = doc.createElement("MANAGEMENT")
                if n['management'] != True:
                    mgmtnode.setAttribute("mode", n['management'])
                physnode.appendChild(mgmtnode)
            if n.get("storage"):
                storagenode = doc.createElement("STORAGE")
                if n['storage'] != True:
                    storagenode.setAttribute("mode", n['storage'])
                physnode.appendChild(storagenode)
            if n.get("vms"):
                vmnode = doc.createElement("VMS")
                physnode.appendChild(vmnode)
            for v in n.get("vlans", []):
                vlannode = doc.createElement("VLAN")
                if "network" in v:
                    vlannode.setAttribute("network", v['network'])
                if "name" in v:
                    vlannode.setAttribute("name", v['name'])
                if v.get("management"):
                    mgmtnode = doc.createElement("MANAGEMENT")
                    if n['management'] != True:
                        mgmtnode.setAttribute("mode", v['management'])
                    vlannode.appendChild(mgmtnode)
                if v.get("storage"):
                    storagenode = doc.createElement("STORAGE")
                    if n['storage'] != True:
                        storagenode.setAttribute("mode", v['storage'])
                    vlannode.appendChild(storagenode)
                if v.get("vms"):
                    vmnode = doc.createElement("VMS")
                    vlannode.appendChild(vmnode)
                physnode.appendChild(vlannode)
            netNode.appendChild(physnode)
        doc.appendChild(netNode)
        return doc

    def handleMultiHostNode(self, node, pool=None):
        i = node.get('start', 0)
        end = node.get('end', None)
        hosts = []
        while xenrt.TEC().lookup("RESOURCE_HOST_%u" % (i), None):
            hnode = copy.deepcopy(node)
            hnode['id'] = i
            host = self.handleHostNode(hnode)
            if pool:
                host["pool"] = pool["name"]
                if not pool["master"]:
                    pool["master"] = "RESOURCE_HOST_%s" % (i)
            hosts.append(host)
            if i == end:
                break
            i = i + 1
        return hosts


    def handleCloudNode(self, node):
        # Load the JSON block from the sequence file
        self.parent.cloudSpec = node


        job = xenrt.GEC().jobid() or "nojob"

        for zone in self.parent.cloudSpec['zones']:
#TODO - Remove
            if not zone.has_key('physical_networks'):
                xenrt.TEC().warning('LEGACY_CLOUD_BLOCK add physical_networks element to legacy cloud block')
                zone['physical_networks'] = [ { "name": "BasicPhyNetwork" } ]

            for pod in zone['pods']:
#TODO - Remove
                if pod.has_key('managementIpRangeSize'):
                    xenrt.TEC().warning('LEGACY_CLOUD_BLOCK managementIpRangeSize no longer valid - use XRT_PodIPRangeSize')
                    pod['XRT_PodIPRangeSize'] = pod.pop('managementIpRangeSize')
                if zone['networktype'] == 'Basic' and not pod.has_key('guestIpRanges'):
                    xenrt.TEC().warning('LEGACY_CLOUD_BLOCK add guestIpRanges element to Basic Zone pods')
                    pod['guestIpRanges'] = [ { } ]
                    
                for cluster in pod['clusters']:
#TODO - Remove
                    if cluster.has_key('hosts'):
                        xenrt.TEC().warning('LEGACY_CLOUD_BLOCK hosts no longer valid - use XRT_Hosts')
                        cluster['XRT_Hosts'] = cluster.pop('hosts')

                    cluster['XRT_NetworkType'] = zone.get("networktype", "Basic")
                    if not cluster.has_key('hypervisor'):
                        cluster['hypervisor'] = "XenServer"

                    currentSysTemplates = xenrt.TEC().lookup("CLOUD_REQ_SYS_TMPLS", None)
                    if not currentSysTemplates:
                        sysTemplates = cluster['hypervisor'].lower()
                    else:
                        curList = currentSysTemplates.split(",")
                        if cluster['hypervisor'].lower() not in curList:
                            curList.append(cluster['hypervisor'].lower())
                        sysTemplates = ",".join(curList)
                    
                    xenrt.TEC().config.setVariable("CLOUD_REQ_SYS_TMPLS", sysTemplates)

                    if cluster['hypervisor'].lower() == "xenserver":
                        if cluster.has_key('XRT_MasterHostId'):
                            cluster['XRT_MasterHostName'] = "RESOURCE_HOST_%d" % cluster['XRT_MasterHostId']
                        if not cluster.has_key('XRT_MasterHostName'):
                            if cluster.has_key('XRT_ContainerHostId'):
                                cluster['XRT_ContainerHostIds'] = [cluster['XRT_ContainerHostId']] * cluster['XRT_Hosts']
                            poolId = self.__minAvailablePool()
                            simplePoolNode = {'id': poolId, 'hosts':[]}
                            
                            poolHosts = []
                            for h in xrange(cluster['XRT_Hosts']):
                                simpleHostNode = {'noisos': True}
                                if cluster.has_key('XRT_ContainerHostIds'):
                                    simpleHostNode['container'] = cluster['XRT_ContainerHostIds'][h]
                                    if cluster.has_key('XRT_vHostMemory'):
                                        if type(cluster['XRT_vHostMemory']) == list:
                                            simpleHostNode['vmemory'] = cluster['XRT_vHostMemory'][h]
                                        else:
                                            simpleHostNode['vmemory'] = cluster['XRT_vHostMemory']
                                else:
                                    hostId = self.__minAvailableHost(poolHosts)
                                    poolHosts.append(int(hostId))
                                    simpleHostNode['id'] = hostId
                                simplePoolNode['hosts'].append(simpleHostNode)

# TODO: Create storage if required                        if cluster.has_key('primaryStorageSRName'):
                            

                            self.handlePoolNode(simplePoolNode)
                            poolSpec = filter(lambda x:x['id'] == str(poolId), self.parent.pools)[0]
                            cluster['XRT_MasterHostName'] = poolSpec['master']
                    elif cluster['hypervisor'].lower() == "kvm":
                        if not cluster.has_key('XRT_KVMHostIds'):
                            hostIds = []
                            for h in xrange(cluster['XRT_Hosts']):
                                hostId = self.__minAvailableHost()
                                hostIds.append(hostId)
                                simpleHostNode = {'id': hostId,
                                                  'product_type': 'kvm',
                                                  'product_version': xenrt.TEC().lookup('CLOUD_KVM_DISTRO', 'rhel63-x64'),
                                                  'noisos': True,
                                                  'install_sr_type': 'no'

                                }
                                self.handleHostNode(simpleHostNode)
                            cluster['XRT_KVMHostIds'] = string.join(map(str, hostIds),',')

                    elif cluster['hypervisor'].lower() == "lxc":
                        if not cluster.has_key('XRT_LXCHostIds'):
                            hostIds = []
                            for h in xrange(cluster['XRT_Hosts']):
                                hostId = self.__minAvailableHost()
                                hostIds.append(hostId)
                                simpleHostNode = {'id': hostId,
                                                  'product_type': 'kvm',
                                                  'product_version': xenrt.TEC().lookup('CLOUD_KVM_DISTRO', 'rhel63-x64'),
                                                  'noisos': True,
                                                  'install_sr_type': 'no'
                                }
                                self.handleHostNode(simpleHostNode)
                            cluster['XRT_LXCHostIds'] = string.join(map(str, hostIds),',')

                    elif cluster['hypervisor'].lower() == "hyperv":
                        if zone.get("networktype", "Basic") == "Advanced" and not zone.has_key('XRT_ZoneNetwork'):
                            zone['XRT_ZoneNetwork'] = "NSEC"
                        if zone.has_key('ipranges'):
                            for i in zone['ipranges']:
                                if not i.has_key("XRT_VlanName"):
                                    i['XRT_VlanName'] = "NSEC"
                        if not cluster.has_key('XRT_HyperVHostIds'):
                            hostIds = []
                            for h in xrange(cluster['XRT_Hosts']):
                                hostId = self.__minAvailableHost()
                                hostIds.append(hostId)
                                simpleHostNode = {'id': hostId,
                                                  'product_type': 'hyperv',
                                                  'product_version': xenrt.TEC().lookup('CLOUD_HYPERV_DISTRO', 'ws12r2-x64'),
                                                  'noisos': True,
                                                  'install_sr_type': 'no',
                                                  'extra_config': {'cloudstack':True}
                                }
                                self.handleHostNode(simpleHostNode)
                            cluster['XRT_HyperVHostIds'] = string.join(map(str, hostIds),',')
                    elif cluster['hypervisor'].lower() == "vmware":
                        if zone.get("networktype", "Basic") == "Advanced" and not zone.has_key('XRT_ZoneNetwork'):
                            zone['XRT_ZoneNetwork'] = "NSEC"
                        if zone.has_key('ipranges'):
                            for i in zone['ipranges']:
                                if not i.has_key("XRT_VlanName"):
                                    i['XRT_VlanName'] = "NSEC"
                        if not zone.has_key('XRT_VMWareDC'):
                            zone['XRT_VMWareDC'] = 'dc-%s-%s' % (uuid.uuid4().hex, job)
                        if not pod.has_key('XRT_VMWareDC'):
                            pod['XRT_VMWareDC'] = zone['XRT_VMWareDC']
                        if not cluster.has_key('XRT_VMWareDC'):
                            cluster['XRT_VMWareDC'] = zone['XRT_VMWareDC']
                        if not cluster.has_key('XRT_VMWareCluster'):
                            cluster['XRT_VMWareCluster'] = 'cluster-%s' % (uuid.uuid4().hex)
                            hostIds = []
                            for h in xrange(cluster['XRT_Hosts']):
                                hostId = self.__minAvailableHost()
                                hostIds.append(hostId)
                                simpleHostNode = {'id': hostId,
                                                  'product_type': 'esx',
                                                  'product_version': xenrt.TEC().lookup('ESXI_VERSION', '5.5.0-update02'),
                                                  'noisos': True,
                                                  'install_sr_type': 'no',
                                                  'extra_config': {"dc": zone['XRT_VMWareDC'], "cluster": cluster['XRT_VMWareCluster'], "virconn": False}
                                }
                                self.handleHostNode(simpleHostNode)
                            cluster['XRT_VMWareHostIds'] = string.join(map(str, hostIds),',')

    def handlePoolNode(self, node):
        pool = {}
        hosts = []

        pool["id"] = str(node.get("id", 0))
        pool["name"] = node.get("name", "RESOURCE_POOL_%s" % (pool["id"]))
        pool["master"] = node.get("master")
        pool["ssl"] = node.get("ssl", False)

        for x in node.get("hosts", []):
            host = self.handleHostNode(x)
            host['pool'] = pool['name']
            hosts.append(host)
            if not pool["master"]:
                if host.has_key("vHostName"):
                    pool["master"] = "vhost-%s" % host["vHostName"]
                else:
                    pool["master"] = "RESOURCE_HOST_%s" % (host["id"])

        if "multihosts" in node:
            hosts.extend(self.handleMultiHostNode(node['multihosts'], pool))

        otherNodes = []
        hasAdvancedNet = False
        self.handleSRs(node, pool['master'])
        self.handleBridges(node, pool['master'])
        for x in node.get("vms", []):
            vm = self.handleVMNode(x)
            vm["host"] = pool["master"] 
            
        for x in node.get("templates", []):
            vm = self.handleVMNode(x, template=True)
            vm["host"] = pool["master"] 
        
        for x in node.get("vm_groups", []):
            vmgroup = self.handleVMGroupNode(x)
            for vm in vmgroup:
                vm["host"] = pool["master"] 
        
        if "network" in node:
            # This is a network topology description we can use
            # with createNetworkTopology. Record the whole DOM node
            self.parent.networksForPools[pool["name"]] = self.handleNetworkNode(node['network'])
            if "controller" in node['network']:
                self.parent.controllersForPools[pool["name"]] = node['network']["controller"]
            hasAdvancedNet = True
        
        self.parent.pools.append(pool)

        if hasAdvancedNet:
            for h in hosts:
                h['basicNetwork'] = False

        return pool

    def handleSRs(self, node, host):
        for x in node.get("srs", []):
            type = x.get("type")
            name = x.get("name")
            default = x.get("default")
            options = x.get("options", "")
            network = x.get("network", "")
            blkbackPoolSize = x.get("blkbackpoolsize", "")
            vmhost = x.get("vmhost", "")
            size = x.get("size", "")
            self.parent.srs.append({"type":type, 
                             "name":name, 
                             "host":host,
                             "default":default,
                             "options":options,
                             "network":network,
                             "blkbackPoolSize":blkbackPoolSize,
                             "vmhost":vmhost,
                             "size":size})

    def handleBridges(self, node, host):
        for x in node.get("bridges", []):
            type = x.get("type", "")
            name = x.get("name", "")
            self.parent.bridges.append({"type":type, 
                                 "name":name, 
                                 "host":host})
        
    def handleHostNode(self, node):
        host = {}        
        host["pool"] = None

        container = node.get("container")
        if container != None:
            host['containerHost'] = int(container)
            host['vHostName'] = node.get("vname", xenrt.randomGuestName())
            host['name'] = node.get("name", "vhost-%s" % host['vHostName'])
            vHostCpus = node.get("vcpus")
            if vHostCpus:
                host['vHostCpus'] = int(vHostCpus)
            vHostMemory = node.get("vmemory")
            if vHostMemory:
                host['vHostMemory'] = int(vHostMemory)
            vHostDiskSize = node.get("vdisksize")
            if vHostDiskSize:
                host['vHostDiskSize'] = int(vHostDiskSize)
            vHostSR = node.get("vsr")
            if vHostSR:
                host['vHostSR'] = vHostSR
            vNetworks = node.get("vnetworks")
            if vNetworks:
                host['vNetworks'] = vNetworks

            if not str(container) in self.parent.containerHosts:
                self.parent.containerHosts.append(str(container))
            
        else:
            host["id"] = str(node['id'])
            host["name"] = node.get("name", str("RESOURCE_HOST_%s" % (host["id"])))
        host["version"] = node.get("version")
        host["productType"] = node.get("product_type", xenrt.TEC().lookup("PRODUCT_TYPE", "xenserver"))
        host["productVersion"] = node.get("product_version")
        host["installSRType"] = node.get("install_sr_type")
        host["dhcp"] = node.get("dhcp", True)
        host['ipv6'] = node.get("ipv6", "")
        host['noipv4'] = node.get("noipv4", False)
        host['diskCount'] = node.get("disk_count", 1)
        host['iommu'] = node.get("iommu", False)
        if "license" in node:
            if node['license'] == True:
                host["license"] = True
            elif node['license'] == False:
                host["license"] = False
            else:
                host["license"] = node['license']
        else:
            ls = xenrt.TEC().lookup("OPTION_LIC_SKU", None)
            if ls:
                host["license"] = ls
        
        if "defaultlicense" in node:
            host["defaultlicense"] = node["defaultlicense"]
        if "noisos" in node:
            host["noisos"] = node.get("noisos", False)
        host["suppackcds"] = node.get("suppackcds")
        if "disablefw" in node:
            host["disablefw"] = node.get("disablefw")
        # cpufreqgovernor is usually one of {userspace, performance, powersave, ondemand}.
        host['cpufreqgovernor'] = node.get("cpufreqgovernor", xenrt.TEC().lookup("CPUFREQ_GOVERNOR", None))
        host['extraConfig'] = node.get("extra_config", {})
        
        hasAdvancedNet = False
        self.handleSRs(node, host['name'])
        self.handleBridges(node, host['name'])

        for x in node.get("vms", []):
            vm = self.handleVMNode(x)
            vm["host"] = host["name"] 
            
        for x in node.get("templates", []):
            vm = self.handleVMNode(x, template=True)
            vm["host"] = host["name"] 
        
        for x in node.get("vm_groups", []):
            vmgroup = self.handleVMGroupNode(x)
            for vm in vmgroup:
                vm["host"] = host["name"]      
            
        if "network" in node:
            # This is a network topology description we can use
            # with createNetworkTopology. Record the whole DOM node
            self.parent.networksForHosts[host["name"]] = self.handleNetworkNode(node['network'])
            if "controller" in node['network']:
                self.parent.controllersForHosts[host["name"]] = node['network']["controller"]
            hasAdvancedNet = True

        host['basicNetwork'] = not hasAdvancedNet

        self.parent.hosts.append(host)

        return host

    def handleUtilityVMNode(self, node):
        vm = self.handleVMNode(node, suffixjob=True)
        vm["host"] = "SHARED"
    
    def handleVLANNode(self, node):
        self.parent.privatevlans.append(node['name'])

    def handleVMGroupNode(self, node):
        vmgroup = []
        basename = node['basename']
        number = node['number']
        for i in range(number):
            x = copy.deepcopy(node)
            del x['basename']
            del x['number']
            x['name'] = "%s-%s" % (basename, i)
            vmgroup.append(self.handleVMNode(x))
        return vmgroup

    def handleVMNode(self, node, suffixjob=False, template=False):
        vm = {} 

        vm["guestname"] = node['name']
        vm["vifs"] = []       
        vm["sriovvifs"] = []
        vm["ips"] = {}       
        vm["disks"] = []
        vm["postinstall"] = []
        if suffixjob:
            vm["suffix"] = xenrt.GEC().dbconnect.jobid()

        if "distro" in node:
            vm['distro'] = node["distro"]
        if "vcpus" in node:
            vm['vcpus'] = node["vcpus"]
        if "cores_per_socket" in node:
            vm['corespersocket'] = node["cores_per_socket"]
        if "memory" in node:
            vm['memory'] = node["memory"]
        if "guestparams" in node:
            vm['guestparams'] = []
            for x in sorted(node['guestparams'].keys()):
                vm['guestparams'].append([x, node['guestparams'], x])
        if "sr" in node:
            vm['sr'] = node["sr"]
        if "arch" in node:
            vm['arch'] = node["arch"]
        for x in node.get("vifs", []):
            if x.get("sriov", False):
                vm["sriovvifs"].append([x.get("physdev"), None])
            else:
                device = x.get("device")
                bridge = x.get("network", "")
                ip = x.get("ip")
                vm["vifs"].append([str(device), bridge, xenrt.randomMAC(), None])
                if ip:
                    vm["ips"][device] = ip
        for x in node.get("disks", []):
            device = x.get("device")
            size = x.get("size")
            format = x.get("format", False)
            number = x.get("count", 1)
            for i in range(int(number)):
                vm["disks"].append([str(device+i), str(size), format])
        for x in node.get("postinstall", []):
            vm['postinstall'].append(x['action'])
        for x in node.get("scripts", []):
            vm['postinstall'].append(self.parent.toplevel.scripts[x])
        if "file_name" in node:
            vm['filename'] = node['file_name']
            vm['userfile'] = node.get("user", False)
        if "boot_params" in node:
            vm['bootparams'] = node['boot_params']
        
        if xenrt.TEC().lookup("DEFAULT_PV_DRIVERS", False, boolean=True) and not "installDrivers" in vm['postinstall'] and not 'filename' in vm:
            vm["postinstall"].append("installDrivers")

        if template and not "convertToTemplate" in vm['postinstall']:
            vm["postinstall"].append("convertToTemplate") 

        self.parent.vms.append(vm)

        return vm

    def handleInstanceNode(self, node, template=False):
        instance = {}

        instance["distro"] = node["distro"]
        if not template:
            instance["name"] = node.get("name")
        instance["zone"] = node.get("zone")
        instance["installTools"] = node.get("install_tools", True)
        instance["hypervisorType"] = node.get("hypervisor_type")
       
        if "vcpus" in node:
            instance['vcpus'] = node['vcpus']
        if "memory" in node:
            instance['memory'] = node['memory']
        if "rootdisk" in node:
            instance['rootdisk'] = node['root_disk']

        if template:
            self.parent.templates.append(instance)
        else:
            self.parent.instances.append(instance)
        return instance

    def handleBlueprintNode(self, node):
        blueprint = {}

        blueprint["name"] = node["name"]
        blueprint["version"] = node["version"]
        blueprint["deploymentProfileTemplateName"] = node["version"]
        if "templateName" in node:
            blueprint["template"] = node["templateName"]

        self.parent.blueprints.append(blueprint)
        return blueprint


class PrepareNodeParserXML(PrepareNodeParserBase):

    def __init__(self, parent, data):
        PrepareNodeParserBase.__init__(self, parent, data)
        self.jsonParser = PrepareNodeParserJSON(self.parent, None)

    def parse(self):
        # Ignore cloud nodes on the first pass
        for n in self.data.childNodes:
            if n.localName == "pool":
                self.handlePoolNode(n)
            elif n.localName == "host":
                self.handleHostNode(n)
            elif n.localName == "sharedhost":
                self.handleSharedHostNode(n)
            elif n.localName == "allhosts":
                # Create a host for each machine known to this job
                if n.hasAttribute("start"):
                    i = int(n.getAttribute("start"))
                else:
                    i = 0
                if n.hasAttribute("stop"):
                    stop = int(n.getAttribute("stop"))
                else:
                    stop = None
                while xenrt.TEC().lookup("RESOURCE_HOST_%u" % (i), None):
                    host = self.handleHostNode(n, id=i)
                    if i == stop:
                        break
                    i = i + 1
            elif n.localName == "template":
                self.handleInstanceNode(n, template=True)
            elif n.localName == "instance":
                self.handleInstanceNode(n, template=False)
            elif n.localName == "vlan":
                self.handleVLANNode(n)
            elif n.localName == "blueprint":
                self.handleBlueprintNode(n)
        
        # Do the cloud nodes now the other hosts have been allocated
        for n in self.data.childNodes:
            if n.localName == "cloud":
                self.handleCloudNode(n)

    def handleCloudNode(self, node):
        self.jsonParser.handleCloudNode(yaml.load(self.expand(node.childNodes[0].data)))
    
    def handlePoolNode(self, node):
        pool = {}

        pool["id"] = self.expand(node.getAttribute("id"))
        if not pool["id"]:
            pool["id"] = 0
        pool["name"] = self.expand(node.getAttribute("name"))
        if not pool["name"]:
            pool["name"] = "RESOURCE_POOL_%s" % (pool["id"])
        pool["master"] = self.expand(node.getAttribute("master"))
        ssl = self.expand(node.getAttribute("ssl"))
        if ssl and ssl[0] in ('y', 't', '1', 'Y', 'T'):
            pool["ssl"] = True
        else:
            pool["ssl"] = False
 
        hostNodes = []   
        otherNodes = []
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "host" or x.localName == "allhosts":
                    hostNodes.append(x)
                else:
                    otherNodes.append(x)

        hosts = []
        # We have to process host elements first, as we may need to
        # determine who the master is (XRT-6100 + XRT-6101)
        for x in hostNodes:
            if x.localName == "host":
                host = self.handleHostNode(x)
                host["pool"] = pool["name"]
                hosts.append(host)
                if not pool["master"]:
                    if host.has_key("vHostName"):
                        pool["master"] = "vhost-%s" % host["vHostName"]
                    else:
                        pool["master"] = "RESOURCE_HOST_%s" % (host["id"])
            elif x.localName == "allhosts":
                # Create a host for each machine known to this job
                if x.hasAttribute("start"):
                    i = int(x.getAttribute("start"))
                else:
                    i = 0
                if x.hasAttribute("stop"):
                    stop = int(x.getAttribute("stop"))
                else:
                    stop = None
                while xenrt.TEC().lookup("RESOURCE_HOST_%u" % (i), None):
                    host = self.handleHostNode(x, id=i)
                    host["pool"] = pool["name"]
                    hosts.append(host)
                    if not pool["master"]:
                        pool["master"] = "RESOURCE_HOST_%s" % (i)
                    if i == stop:
                        break
                    i = i + 1
        hasAdvancedNet = False
        for x in otherNodes:
            if x.localName == "storage":
                type = self.expand(x.getAttribute("type"))
                name = self.expand(x.getAttribute("name"))
                default = self.expand(x.getAttribute("default"))
                options = self.expand(x.getAttribute("options"))
                network = self.expand(x.getAttribute("network"))
                blkbackPoolSize = self.expand(x.getAttribute("blkbackpoolsize"))
                vmhost = self.expand(x.getAttribute("vmhost"))
                size = self.expand(x.getAttribute("size"))
                self.parent.srs.append({"type":type, 
                                 "name":name, 
                                 "host":pool["master"],
                                 "default":(lambda x:x == "true")(default),
                                 "options":options,
                                 "network":network,
                                 "blkbackPoolSize":blkbackPoolSize,
                                 "vmhost":vmhost,
                                 "size":size})
            elif x.localName == "bridge":
                type = self.expand(x.getAttribute("type"))
                name = self.expand(x.getAttribute("name"))
                self.parent.bridges.append({"type":type, 
                                     "name":name, 
                                     "host":pool["master"]})
            elif x.localName == "vm":
                vm = self.handleVMNode(x)
                vm["host"] = pool["master"] 
            elif x.localName == "template":
                vm = self.handleVMNode(x, template=True)
                vm["host"] = pool["master"] 
            elif x.localName == "vmgroup":
                vmgroup = self.handleVMGroupNode(x)
                for vm in vmgroup:
                    vm["host"] = host["name"]      
            elif x.localName == "NETWORK":
                # This is a network topology description we can use
                # with createNetworkTopology. Record the whole DOM node
                if x.getAttribute("controller"):
                    self.parent.controllersForPools[pool["name"]] = self.expand(x.getAttribute("controller"))
                self.parent.networksForPools[pool["name"]] = x.parentNode
                hasAdvancedNet = True
        self.parent.pools.append(pool)

        if hasAdvancedNet:
            for h in hosts:
                h['basicNetwork'] = False

        return pool

    def handleHostNode(self, node, id=0):
        host = {}        
        host["pool"] = None

        host["name"] = self.expand(node.getAttribute("alias"))
        container = self.expand(node.getAttribute("container"))
        if container:
            containerHost = int(container)
            host['containerHost'] = containerHost
            host['vHostName'] = self.expand(node.getAttribute("vname"))
            if not host['vHostName']:
                host['vHostName'] = xenrt.randomGuestName()
            if not host['name']:
                host['name'] = "vhost-%s" % host['vHostName']
            vHostCpus = self.expand(node.getAttribute("vcpus"))
            if vHostCpus:
                host['vHostCpus'] = int(vHostCpus)
            vHostMemory = self.expand(node.getAttribute("vmemory"))
            if vHostMemory:
                host['vHostMemory'] = int(vHostMemory)
            vHostDiskSize = self.expand(node.getAttribute("vdisksize"))
            if vHostDiskSize:
                host['vHostDiskSize'] = int(vHostDiskSize)
            vHostSR = self.expand(node.getAttribute("vsr"))
            if vHostSR:
                host['vHostSR'] = vHostSR
            vNetworks = self.expand(node.getAttribute("vnetworks"))
            if vNetworks:
                host['vNetworks'] = vNetworks.split(",")

            if not container in self.parent.containerHosts:
                self.parent.containerHosts.append(container)
        else:
            host["id"] = self.expand(node.getAttribute("id"))
            if not host["id"]:
                host["id"] = str(id)
            if not host["name"]:
                host["name"] = str("RESOURCE_HOST_%s" % (host["id"]))
        host["version"] = self.expand(node.getAttribute("version"))
        if not host["version"] or host["version"] == "DEFAULT":
            host["version"] = None
        host["productType"] = self.expand(node.getAttribute("productType"))
        if not host["productType"]:
            host["productType"] = xenrt.TEC().lookup("PRODUCT_TYPE", "xenserver")
        host["productVersion"] = self.expand(node.getAttribute("productVersion"))
        if not host["productVersion"] or host["productVersion"] == "DEFAULT":
            host["productVersion"] = None
        host["installSRType"] = self.expand(node.getAttribute("installsr"))
        if not host["installSRType"]:
            host["installSRType"] = None
        dhcp = self.expand(node.getAttribute("dhcp"))
        if not dhcp:
            host["dhcp"] = True
        elif dhcp[0] in ('y', 't', '1', 'Y', 'T'):
            host["dhcp"] = True
        else:
            host["dhcp"] = False
        host['ipv6'] = self.expand(node.getAttribute("ipv6"))
        noipv4 = self.expand(node.getAttribute("noipv4"))
        if not noipv4:
            host['noipv4'] = False
        elif noipv4[0] in set(['y', 't', '1', 'Y', 'T']):
            host['noipv4'] = True
        if not host['ipv6']:
            host['noipv4'] = False
        dc = self.expand(node.getAttribute("diskCount"))
        if not dc:
            dc = "1"
        host["diskCount"] = int(dc)
        license = self.expand(node.getAttribute("license"))
        if license:
            if license[0] in ('y', 't', '1', 'Y', 'T'):
                host["license"] = True
            elif license[0] in ('n', 'f', '0', 'N', 'F'):
                host["license"] = False
            else:
                host["license"] = license
        else:
            ls = xenrt.TEC().lookup("OPTION_LIC_SKU", None)
            if ls:
                host["license"] = ls
        defaultlicense = self.expand(node.getAttribute("defaultlicense"))
        if defaultlicense:
            if defaultlicense[0] in ('y', 't', '1', 'Y', 'T'):
                host["defaultlicense"] = True
            else:
                host["defaultlicense"] = False
        noisos = self.expand(node.getAttribute("noisos"))
        if noisos:
            if noisos[0] in ('y', 't', '1', 'Y', 'T'):
                host["noisos"] = True
            else:
                host["noisos"] = False
        defaultHost = self.expand(node.getAttribute("default"))
        if defaultHost and defaultHost[0] in ('y', 't', '1', 'Y', 'T'):
            host['default'] = True
        host["suppackcds"] = self.expand(node.getAttribute("suppackcds"))
        iommu = self.expand(node.getAttribute("iommu"))
        if iommu:
            if iommu[0] in ('y', 't', '1', 'Y', 'T'):
                host["iommu"] = True
            else:
                host["iommu"] = False
        else:
            host["iommu"] = False
        disablefw = self.expand(node.getAttribute("disablefw"))
        if disablefw:
            if disablefw[0] in ('y', 't', '1', 'Y', 'T'):
                host["disablefw"] = True
            else:
                host["disablefw"] = False
        if not host["suppackcds"]:
            host["suppackcds"] = None
        # cpufreqgovernor is usually one of {userspace, performance, powersave, ondemand}.
        cpufreqGovernor = self.expand(node.getAttribute("cpufreqgovernor"))
        if cpufreqGovernor:
            host["cpufreqgovernor"] = cpufreqGovernor
        else:
            host["cpufreqgovernor"] = xenrt.TEC().lookup("CPUFREQ_GOVERNOR", None)
        extraCfg = self.expand(node.getAttribute("extraConfig"))
        if not extraCfg:
            host['extraConfig'] = {}
        else:
            host['extraConfig'] = yaml.load(extraCfg)
        
        hasAdvancedNet = False
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "storage":
                    type = self.expand(x.getAttribute("type"))
                    name = self.expand(x.getAttribute("name"))
                    default = self.expand(x.getAttribute("default"))
                    options = self.expand(x.getAttribute("options"))
                    network = self.expand(x.getAttribute("network"))
                    blkbackPoolSize = self.expand(x.getAttribute("blkbackpoolsize"))
                    vmhost = self.expand(x.getAttribute("vmhost"))
                    size = self.expand(x.getAttribute("size"))
                    self.parent.srs.append({"type":type, 
                                     "name":name, 
                                     "host":host["name"],
                                     "default":(lambda x:x == "true")(default),
                                     "options":options,
                                     "network":network,
                                     "blkbackPoolSize":blkbackPoolSize,
                                     "vmhost":vmhost,
                                     "size":size})
                elif x.localName == "bridge":
                    type = self.expand(x.getAttribute("type"))
                    name = self.expand(x.getAttribute("name"))
                    self.parent.bridges.append({"type":type, 
                                         "name":name, 
                                         "host":host['name']})
                elif x.localName == "vm":
                    vm = self.handleVMNode(x)
                    vm["host"] = host["name"] 
                elif x.localName == "template":
                    vm = self.handleVMNode(x, template=True)
                    vm["host"] = host["name"] 
                elif x.localName == "vmgroup":
                    vmgroup = self.handleVMGroupNode(x)
                    for vm in vmgroup:
                        vm["host"] = host["name"]      
                elif x.localName == "NETWORK":
                    # This is a network topology description we can use
                    # with createNetworkTopology. Record the whole DOM node
                    self.parent.networksForHosts[host["name"]] = x.parentNode
                    if x.getAttribute("controller"):
                        self.parent.controllersForHosts[host["name"]] = self.expand(x.getAttribute("controller"))
                    hasAdvancedNet = True
        host['basicNetwork'] = not hasAdvancedNet

        self.parent.hosts.append(host)

        return host

    def handleSharedHostNode(self, node):
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "vm":
                    vm = self.handleVMNode(x, suffixjob=True)
                    vm["host"] = "SHARED" 
    
    def handleVLANNode(self, node):
        self.parent.privatevlans.append(self.expand(node.getAttribute("name")))
    
    def handleVMGroupNode(self, node):
        vmgroup = []
        basename = self.expand(node.getAttribute("basename"))
        number = self.expand(node.getAttribute("number"))
        for i in range(int(number)):
            node.setAttribute("name", "%s-%s" % (basename, i))
            vmgroup.append(self.handleVMNode(node))
        return vmgroup

    def handleVMNode(self, node, suffixjob=False, template=False):
        vm = {} 

        vm["guestname"] = self.expand(node.getAttribute("name"))
        vm["vifs"] = []       
        vm["sriovvifs"] = []
        vm["ips"] = {}       
        vm["disks"] = []
        vm["postinstall"] = []
        if suffixjob:
            vm["suffix"] = xenrt.GEC().dbconnect.jobid()
 
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "distro":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["distro"] = self.expand(str(a.data))
                elif x.localName == "vcpus":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["vcpus"] = int(self.expand(str(a.data)))
                elif x.localName == "corespersocket":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["corespersocket"] = int(self.expand(str(a.data)))
                elif x.localName == "memory":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["memory"] = int(self.expand(str(a.data)))
                elif x.localName == "guestparams":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["guestparams"] = map(lambda x:x.split('='),  string.split(self.expand(str(a.data)), ","))
                elif x.localName == "storage":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["sr"] = self.expand(str(a.data))
                elif x.localName == "arch":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["arch"] = self.expand(str(a.data))
                elif x.localName == "network":
                    sriov = self.expand(x.getAttribute("sriov"))
                    if sriov == "true" or sriov == "yes":
                        physdev = self.expand(x.getAttribute("physdev"))
                        vm["sriovvifs"].append([physdev, None])
                    else:
                        device = self.expand(x.getAttribute("device"))
                        bridge = self.expand(x.getAttribute("bridge"))
                        ip = self.expand(x.getAttribute("ip"))
                        vm["vifs"].append([device, bridge, xenrt.randomMAC(), None])
                        if ip:
                            vm["ips"][int(device)] = ip
                elif x.localName == "disk":
                    device = self.expand(x.getAttribute("device"))
                    size = self.expand(x.getAttribute("size"))
                    format = self.expand(x.getAttribute("format"))
                    number = self.expand(x.getAttribute("number"))
                    if format == "true" or format == "yes": 
                        format = True
                    else: format = False
                    if not number: number = 1
                    for i in range(int(number)):
                        vm["disks"].append([str(int(device)+i), size, format])
                elif x.localName == "postinstall":
                    action = self.expand(x.getAttribute("action"))
                    vm["postinstall"].append(action)
                elif x.localName == "script":
                    name = self.expand(x.getAttribute("name"))
                    vm["postinstall"].append(self.parent.toplevel.scripts[name])
                elif x.localName == "file":
                    usertext = self.expand(x.getAttribute("user"))
                    vm["userfile"] = usertext == "true" or usertext == "yes"
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["filename"] = self.expand(str(a.data))
                elif x.localName == "bootparams":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["bootparams"] = self.expand(str(a.data))
                elif x.localName == "packages":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            vm["packages"] = self.expand(str(a.data)).split(",")

        if xenrt.TEC().lookup("DEFAULT_PV_DRIVERS", False, boolean=True) and not "installDrivers" in vm['postinstall'] and not 'filename' in vm:
            vm["postinstall"].append("installDrivers")

        if template and not "convertToTemplate" in vm['postinstall']:
            vm["postinstall"].append("convertToTemplate") 

        self.parent.vms.append(vm)

        return vm

    def handleInstanceNode(self, node, template=False):
        instance = {}

        instance["distro"] = self.expand(node.getAttribute("distro"))
        if not template:
            instance["name"] = self.expand(node.getAttribute("name"))
        instance["zone"] = self.expand(node.getAttribute("zone"))
        instance["installTools"] = node.getAttribute("installTools") is None or node.getAttribute("installTools")[0] in ('y', 't', '1', 'Y', 'T')
        instance["hypervisorType"] = self.expand(node.getAttribute("hypervisorType"))
        
        # TODO: vifs
        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "vcpus":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            instance["vcpus"] = int(self.expand(str(a.data)))
                elif x.localName == "memory":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            instance["memory"] = int(self.expand(str(a.data)))
                elif x.localName == "rootdisk":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            instance["rootdisk"] = int(self.expand(str(a.data)))

        if template:
            self.parent.templates.append(instance)
        else:
            self.parent.instances.append(instance)
        return instance

    def handleBlueprintNode(self, node):
        blueprint = {}
        blueprint["name"] = self.expand(node.getAttribute("name"))
        blueprint["version"] = self.expand(node.getAttribute("version"))
        blueprint["deploymentProfileTemplateName"] = self.expand(node.getAttribute("deploymentProfileTemplateName"))

        for x in node.childNodes:
            if x.nodeType == x.ELEMENT_NODE:
                if x.localName == "templateName":
                    for a in x.childNodes:
                        if a.nodeType == a.TEXT_NODE:
                            blueprint["template"] = self.expand(str(a.data))

        self.parent.blueprints.append(blueprint)
        return blueprint

class PrepareNode(object):

    def __init__(self, toplevel, node, params):
        self.toplevel = toplevel
        self.vms = []
        self.templates = []
        self.instances = []
        self.hosts = []
        self.pools = []
        self.bridges = []
        self.srs = []
        self.privatevlans = []
        self.cloudSpec = {}
        self.networksForHosts = {}
        self.networksForPools = {}
        self.controllersForHosts = {}
        self.controllersForPools = {}
        self.preparecount = 0
        self.params = params
        self.containerHosts = []
        self.blueprints = []

        parser = None
        for n in node.childNodes:
            if n.nodeType == n.TEXT_NODE and n.data.strip():
                parser = xenrt.seq.PrepareNodeParserJSON(self, yaml.load(n.data))
                break

        if not parser:
            parser = xenrt.seq.PrepareNodeParserXML(self, node)

        parser.parse()

        # Insert preprepare if required for any containerHosts
        if len(self.containerHosts) > 0 and self.toplevel.preprepare is None \
           and node.localName != "preprepare":
            xenrt.TEC().logverbose("Creating preprepare node becuase we have nested hosts")
            preprepareNode = xml.dom.minidom.Element("preprepare")
            for c in self.containerHosts:
                hostNode = xml.dom.minidom.Element("host")
                hostNode.setAttribute("id", c)
                preprepareNode.appendChild(hostNode)
            self.toplevel.preprepare = PrepareNode(self.toplevel, preprepareNode, params)

    def chooseISOSRType(self, host, sr):
        # Check what the SR supports
        if not sr.get("cifspath"):
            return "nfs"
        if not sr.get("nfspath"):
            return "cifs"
        
        # Check what the host supports
        lib = xenrt.productLib(host=host)
        if not hasattr(lib, "CIFSISOStorageRepository"):
            return "nfs"
        if not hasattr(lib, "ISOStorageRepository"):
            return "cifs"

        # Both the SR and the host can do CIFS and NFS. So now check whether we've selected one in this job
        with xenrt.GEC().getLock("ISO_SR_TYPE"):
            ret = xenrt.TEC().lookup("ISO_SR_TYPE", None)
            if not ret:
                ret = random.choice(("cifs", "nfs"))
                xenrt.GEC().config.setVariable("ISO_SR_TYPE", ret)
                xenrt.GEC().dbconnect.jobUpdate("ISO_SR_TYPE",ret)
            return ret


    def debugDisplay(self):
        xenrt.TEC().logverbose("Hosts:\n" + pprint.pformat(self.hosts))
        xenrt.TEC().logverbose("Pools:\n" + pprint.pformat(self.pools))
        xenrt.TEC().logverbose("VMs:\n" + pprint.pformat(self.vms))
        xenrt.TEC().logverbose("Bridges:\n" + pprint.pformat(self.bridges))
        xenrt.TEC().logverbose("SRs:\n" + pprint.pformat(self.srs))
        xenrt.TEC().logverbose("Cloud Spec:\n" + pprint.pformat(self.cloudSpec))
        xenrt.TEC().logverbose("Templates:\n" + pprint.pformat(self.templates))
        xenrt.TEC().logverbose("Instances:\n" + pprint.pformat(self.instances))
        xenrt.TEC().logverbose("Blueprints:\n" + pprint.pformat(self.blueprints))

    def getAllPoolHostsForMaster(self, host):
        ret = [host]
        for p in self.pools:
            if host.getName() == p['master']:
                ret = [xenrt.TEC().registry.hostGet(x) for x in self.hosts if x['pool'] == p['name']]
        return ret

    def runThis(self):
        self.preparecount = self.preparecount + 1
        xenrt.TEC().logdelimit("Sequence setup")
        self.debugDisplay()

        nohostprepare = xenrt.TEC().lookup(["CLIOPTIONS", "NOHOSTPREPARE"],
                                         False,
                                         boolean=True)

        if not nohostprepare:
            # Get rid of the old CCP management servers, and the info about them
            xenrt.TEC().logverbose("Resetting machine info")
            i = 0
            cleanedGuests = []
            while True:
                try:
                    hostname = xenrt.TEC().lookup("RESOURCE_HOST_%d" % i)
                except:
                    break
                # Try to delete the old CCP management server
                try:
                    m = xenrt.GEC().dbconnect.api.get_machine(hostname)['params']
                    if m.has_key("CSGUEST") and m['CSGUEST'] not in cleanedGuests:
                        cleanedGuests.append(m['CSGUEST'])
                        (shostname, guestname) = m['CSGUEST'].split("/", 1)
                        host = xenrt.SharedHost(shostname, doguests = True).getHost()
                        guest = host.guests[guestname]
                        guest.uninstall()
                except Exception, e:
                    xenrt.TEC().logverbose("Could not clean Cloudstack management server - %s" % str(e))
                # Reset the machine info 
                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [hostname, "CSIP", ""])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [hostname, "CSGUEST", ""])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [hostname, "WINDOWS", ""])
                except:
                    pass
                i += 1
        
        try:
            for v in self.privatevlans:
                xenrt.GEC().registry.vlanPut(v, xenrt.PrivateVLAN())
            sharedGuestQueue = InstallWorkQueue()
            for v in self.vms:
                if v.has_key("host") and v["host"] == "SHARED":
                    if not xenrt.TEC().registry.hostGet("SHARED"):
                        xenrt.TEC().registry.hostPut("SHARED", xenrt.resources.SharedHost().getHost())
                    sharedGuestQueue.add(v)
                
            sharedGuestWorkers = []
            if len(sharedGuestQueue.items) > 0:
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = GuestInstallWorker(sharedGuestQueue, name="SHGWorker%02u" % (i))
                    sharedGuestWorkers.append(w)
                    w.start()
                
            if not nohostprepare:
                # Install hosts in parallel to save time.
                queue = InstallWorkQueue()
                for h in self.hosts:
                    queue.add(h)
                workers = []
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = HostInstallWorker(queue, name="HWorker%02u" % (i))
                    workers.append(w)
                    w.start()
                    # There appears to be a strange race condition somewhere, which
                    # results in NFS directory paths getting confused, and multiple
                    # installs sharing the same completion dir! While locating it,
                    # this should prevent any problems
                    xenrt.sleep(30)
                for w in workers:
                    w.join()
                for w in workers:
                    if w.exception:
                        exc_type, exc_value, exc_traceback = w.exception_extended
                        raise exc_type, exc_value, exc_traceback

                # Work out which hosts are masters and which are going to be
                # slaves. We'll do the actual pooling later.
                slaves = []
                # Check each pool for slaves
                for p in self.pools:
                    slaves.extend(filter(lambda x:x["pool"] == p["name"] \
                                         and not x["name"] == p["master"],
                                         self.hosts))
                masters = filter(lambda x:x not in slaves, self.hosts)

                # If we have a detailed network topology set this up on the
                # master(s) now
                for master in masters:
                    if master["pool"]:
                        if self.networksForPools.has_key(master["pool"]):
                            host = xenrt.TEC().registry.hostGet(master["name"])
                            t = self.networksForPools[master["pool"]]
                            host.createNetworkTopology(t)
                            host.checkNetworkTopology(t)
                    else:
                        if self.networksForHosts.has_key(master["name"]):
                            host = xenrt.TEC().registry.hostGet(master["name"])
                            t = self.networksForHosts[master["name"]]
                            host.createNetworkTopology(t)
                            host.checkNetworkTopology(t)

                # Perform any pre-pooling network setup on slaves
                if xenrt.TEC().lookup("WORKAROUND_CA21810", False, boolean=True):
                    xenrt.TEC().warning("Using CA-21810 workaround")
                    for p in self.pools:
                        if self.networksForPools.has_key(p["name"]):
                            slaves = filter(lambda x:x["pool"] == p["name"] \
                                            and not x["name"] == p["master"],
                                            self.hosts)
                            for s in slaves:
                                t = self.networksForPools[s["pool"]]
                                host = xenrt.TEC().registry.hostGet(s["name"])
                                host.presetManagementInterfaceForTopology(t)

                # Create network bridges.
                for b in self.bridges:
                    host = xenrt.TEC().registry.hostGet(b["host"]) 
                    host.createNetwork(b["name"])

                # Add ISO SRs to pool masters and independent hosts.
                # This should only be done on the first prepare and not on
                # subsequent re-prepares.
                if self.preparecount == 1:
                    for host in masters:
                        if not host.get("noisos") and not xenrt.TEC().lookup("NO_ISO_SRS", False, boolean=True):
                            self.srs.insert(0, {"host":host["name"], 
                                                "name":"XenRT ISOs",
                                                "type":"iso",
                                                "nfspath":xenrt.TEC().lookup("EXPORT_ISO_NFS"),
                                                "cifspath": xenrt.TEC().lookup("EXPORT_ISO_CIFS", None),
                                                "default":False,
                                                "blkbackPoolSize":""})
                            isos2 = xenrt.TEC().lookup("EXPORT_ISO_NFS_STATIC", None)
                            if isos2:
                                self.srs.insert(0, {"host":host["name"],
                                                    "name":"XenRT static ISOs",
                                                    "type":"iso",
                                                    "nfspath":isos2,
                                                    "cifspath": xenrt.TEC().lookup("EXPORT_ISO_CIFS_STATIC", None),
                                                    "default":False,
                                                    "blkbackPoolSize":""})
                            if xenrt.TEC().lookup("USE_PREBUILT_TEMPLATES", False, boolean=True):
                                self.srs.insert(0, {"type": "nfstemplate", "host": host['name'], "default": False, "blkbackPoolSize": ""})

                # If needed, create lun groups
                iscsihosts = {}
                for s in self.srs:
                    if (s["type"] == "lvmoiscsi" or s["type"] == "extoiscsi") and not ((s["options"] and "ietvm" in s["options"].split(",")) or (s["options"] and "iet" in s["options"].split(","))):
                        if not iscsihosts.has_key(s["host"]):
                            iscsihosts[s["host"]] = 0
                        iscsihosts[s["host"]] += 1
                for h in iscsihosts.keys():
                    if iscsihosts[h] > 1:
                        # There are multiple iSCSI SRs for this host, we need a lun group
                        host = xenrt.TEC().registry.hostGet(h) 
                        minsize = int(host.lookup("SR_ISCSI_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_ISCSI_MAXSIZE", 1000000))
                        # For now we don't support jumbo frames for lun groups in sequence files
                        host.lungroup = xenrt.resources.ISCSILunGroup(iscsihosts[h], jumbo=False, minsize=minsize, maxsize=maxsize)
                        host.setIQN(host.lungroup.getInitiatorName(allocate=True))

                # Create SRs.
                for s in self.srs:
                    host = xenrt.TEC().registry.hostGet(s["host"]) 
                    if s["type"] == "lvmoiscsi":
                        smconf = {}
                        thinProv = False
                        if s["options"]:
                            options = s["options"].split(",")
                            if "thin" in options:
                                thinProv = True
                                thin_init = None
                                thin_quan = None
                                for opt in options:
                                    if opt.startswith("thin_init:"):
                                        thin_init = opt[len("thin_init:"):]
                                    if opt.startswith("thin_quan:"):
                                        thin_quan = opt[len("thin_quan:"):]
                                thin_init = xenrt.TEC().lookup("THIN_INITIAL_ALLOCATION", thin_init)
                                thin_quan = xenrt.TEC().lookup("THIN_ALLOCATION_QUANTUM", thin_quan)
                                if thin_init:
                                    smconf["initial_allocation"] = thin_init
                                if thin_quan:
                                    smconf["allocation_quantum"] = thin_quan
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr = xenrt.productLib(host=host).ISCSIStorageRepository(host, s["name"], thinProv)
                        if s["options"] and "iet" in s["options"].split(","):
                            # Create the SR using an IET LUN from the controller
                            lun = xenrt.ISCSITemporaryLun(300)
                            sr.create(lun, subtype="lvm", multipathing=mp, noiqnset=True, findSCSIID=True, smconf=smconf)
                        elif s["options"] and "ietvm" in s["options"].split(","):
                            # Create the SR using an IET LUN from the controller
                            lun = xenrt.ISCSIVMLun(s["vmhost"],int(s["size"])*xenrt.KILO)
                            sr.create(lun, subtype="lvm", multipathing=mp, noiqnset=True, findSCSIID=True, smconf=smconf)
                        else:
                            if s["options"] and "jumbo" in s["options"].split(","):
                                jumbo = True
                            else:
                                jumbo = False
                            if s["options"] and "mpprdac" in s["options"].split(","):
                                mpp_rdac = True
                            else:
                                mpp_rdac = False
                            initiatorcount = None
                            if s["options"]:
                                for o in s["options"].split(","):
                                    m = re.match("initiatorcount=(\d+)", o)
                                    if m:
                                        initiatorcount = int(m.group(1))
                            sr.create(subtype="lvm", multipathing=mp, jumbo=jumbo, mpp_rdac=mpp_rdac, initiatorcount=initiatorcount, smconf=smconf)
                    elif s["type"] == "extoscsi":
                        sr = xenrt.productLib(host=host).ISCSIStorageRepository(host, s["name"])
                        if s["options"] and "jumbo" in s["options"].split(","):
                            jumbo = True
                        else:
                            jumbo = False
                        sr.create(subtype="ext", jumbo=jumbo)
                    elif s["type"] == "nfs":
                        if s["options"] and "jumbo" in s["options"].split(","):
                            jumbo = True
                        else:
                            jumbo = False
                        if s["options"] and "nosubdir" in s["options"].split(","):
                            nosubdir = True
                        else:
                            nosubdir = False
                        if s["options"] and "filesr" in s["options"].split(","):
                            filesr = True
                        else:
                            filesr = False
                        if s["network"]:
                            network = s["network"]
                        else:
                            network = "NPRI"
                        if s["options"] and "v4" in s["options"].split(","):
                            nfsVersion = "4"
                        else:
                            nfsVersion = "3"

                        hostIndexes = [(y.group(1), y.group(3)) for y in [re.match("host-(\d)(-([a-z]*))?", x) for x in s['options'].split(",")] if y]
                        if hostIndexes:
                            (hostIndex, device) = hostIndexes[0]
                            server, path = xenrt.NativeLinuxNFSShare("RESOURCE_HOST_%s" % hostIndex, device=device).getMount().split(":")
                        else:
                            server, path = xenrt.ExternalNFSShare(jumbo=jumbo, network=network, version=nfsVersion).getMount().split(":")

                        if filesr:
                            sr = xenrt.productLib(host=host).FileStorageRepositoryNFS(host, s["name"])
                            sr.create(server, path)
                        else:
                            if nfsVersion == "4":
                                sr = xenrt.productLib(host=host).NFSv4StorageRepository(host, s["name"])
                            else:
                                sr = xenrt.productLib(host=host).NFSStorageRepository(host, s["name"])
                            sr.create(server, path, nosubdir=nosubdir)
                    elif s["type"] == "smb":
                        vm = s["options"] and "vm" in s["options"].split(",")
                        cifsuser = s["options"] and "cifsuser" in s["options"].split(",")
                        hostIndexes = [(y.group(1), y.group(3)) for y in [re.match("host-(\d)(-([a-z]))?", x) for x in s['options'].split(",")] if y]
                        if hostIndexes:
                            (hostIndex, driveLetter) = hostIndexes[0]
                            share = xenrt.NativeWindowsSMBShare("RESOURCE_HOST_%s" % hostIndex, driveLetter=driveLetter)
                        elif vm:
                            share = xenrt.VMSMBShare()
                        elif cifsuser:
                            share = xenrt.ExternalSMBShare(version=3, cifsuser="cifsuser")
                        else:
                            share = xenrt.ExternalSMBShare(version=3)
                        sr = xenrt.productLib(host=host).SMBStorageRepository(host, s["name"])
                        if cifsuser:
                            sr.create(share, "cifsuser")
                        else:
                            sr.create(share)
                    elif s["type"] == "iso":
                        srtype = self.chooseISOSRType(host, s)
                        if srtype == "nfs":
                            sr = xenrt.productLib(host=host).ISOStorageRepository(host, s["name"])
                            server, path = s["nfspath"].split(":")
                            sr.create(server, path)
                        elif srtype == "cifs":
                            sr = xenrt.productLib(host=host).CIFSISOStorageRepository(host, s["name"])
                            (username, password, path) = s["cifspath"].split(":")
                            m = re.match("\\\\\\\\(.+?)\\\\(.+)", path)
                            server = m.group(1)
                            share = m.group(2)
                            sr.create(server, share, username=username, password=password)
                        sr.scan()
                    elif s['type'] == "nfstemplate":
                        try:
                            sr = host.createTemplateSR()
                        except Exception, e:
                            # This is only best effort
                            xenrt.TEC().logverbose("Warning - could not add remote template library: %s" % str(e))
                            continue
                    elif s["type"] == "netapp":
                        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                        if s.has_key("options") and s["options"]:
                            options = s["options"]
                        else:
                            options = None
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).NetAppStorageRepository(host, s["name"])
                        sr.create(napp, options=options, multipathing=mp)
                    elif s["type"] == "eql" or s["type"] == "equal":
                        minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                        if s.has_key("options") and s["options"]:
                            options = s["options"]
                        else:
                            options = None
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        eql = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).EQLStorageRepository(host, s["name"])
                        sr.create(eql, options=options, multipathing=mp)
                    elif s["type"] == "fc":
                        thinProv = False
                        smconf = {}
                        if s.has_key("options") and s["options"]:
                            options = s["options"].split(",")
                            if "thin" in options:
                                thinProv = True
                                thin_init = None
                                thin_quan = None
                                for opt in options:
                                    if opt.startswith("thin_init:"):
                                        thin_init = opt[len("thin_init:"):]
                                    if opt.startswith("thin_quan:"):
                                        thin_quan = opt[len("thin_quan:"):]
                                thin_init = xenrt.TEC().lookup("THIN_INITIAL_ALLOCATION", thin_init)
                                thin_quan = xenrt.TEC().lookup("THIN_ALLOCATION_QUANTUM", thin_quan)
                                if thin_init:
                                    smconf["initial_allocation"] = thin_init
                                if thin_quan:
                                    smconf["allocation_quantum"] = thin_quan
                        sr = xenrt.productLib(host=host).FCStorageRepository(host, s["name"], thinProv)
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        lun = xenrt.HBALun(self.getAllPoolHostsForMaster(host)) 
                        sr.create(lun, multipathing=mp, smconf=smconf)
                    elif s["type"] == "cvsmnetapp":
                        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(napp)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  napp,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmeql":
                        minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                        napp = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(napp)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  napp,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmfc":
                        fchba = xenrt.FCHBATarget()
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(fchba)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  fchba,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmsmisiscsi":
                        minsize = int(host.lookup("SR_SMIS_ISCSI_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_SMIS_ISCSI_MAXSIZE", 1000000))
                        smisiscsi = xenrt.SMISiSCSITarget()
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(smisiscsi)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  smisiscsi,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "cvsmsmisfc":
                        minsize = int(host.lookup("SR_SMIS_FC_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_SMIS_FC_MAXSIZE", 1000000))
                        smisfc = xenrt.SMISFCTarget(minsize=minsize, maxsize=maxsize)
                        cvsmserver = xenrt.CVSMServer(\
                            xenrt.TEC().registry.guestGet("CVSMSERVER"))
                        cvsmserver.addStorageSystem(smisfc)
                        sr = xenrt.productLib(host=host).CVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(cvsmserver,
                                  smisfc,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmnetapp":
                        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(napp,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmeql":
                        minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                        maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                        eql = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(eql,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmfc":
                        fchba = xenrt.FCHBATarget()
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(fchba,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmsmisiscsi":
                        smisiscsi = xenrt.SMISiSCSITarget()
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(smisiscsi,
                                  protocol="iscsi",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s["type"] == "icvsmsmisfc":
                        smisfc = xenrt.SMISFCTarget()
                        sr = xenrt.productLib(host=host).IntegratedCVSMStorageRepository(\
                            host, s["name"])
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        sr.create(smisfc,
                                  protocol="fc",
                                  physical_size=None,
                                  multipathing=mp)
                    elif s['type'] == "smapiv3local" or s['type'] == "btrfs":
                        sr = xenrt.productLib(host=host).SMAPIv3LocalStorageRepository(host, s['name'])
                        device = s['options'] or None
                        sr.create(device, content_type="user")
                    elif s["type"] == "fcoe":
                        thinProv = False
                        if s.has_key("options") and s["options"] and "thin" in s["options"].split(","):
                            thinProv = True
                        sr = xenrt.productLib(host=host).FCOEStorageRepository(host, s["name"], thinProv)
                        if host.lookup("USE_MULTIPATH", False, boolean=True):
                            mp = True
                        else:
                            mp = None
                        
                        lun = xenrt.HBALun(self.getAllPoolHostsForMaster(host)) 
                        sr.create(lun, multipathing=mp)
                    elif s['type'] == "smapiv3shared" or s['type'] == "rawnfs":
                        if s["network"]:
                            network = s["network"]
                        else:
                            network = "NPRI"

                        sr = xenrt.productLib(host=host).SMAPIv3SharedStorageRepository(host, s['name'])
                        sr.create(None, None)
                    else:
                        raise xenrt.XRTError("Unknown storage type %s" % (s["type"]))
                    #change blkback pool size
                    if s["blkbackPoolSize"]:
                        sr.paramSet(paramName="other-config:mem-pool-size-rings", paramValue=s["blkbackPoolSize"])
                    host.addSR(sr, default=s["default"])
                    if s["default"]:
                        p = host.minimalList("pool-list")[0]
                        host.genParamSet("pool", p, "default-SR", sr.uuid)
                        host.genParamSet("pool", p, "crash-dump-SR", sr.uuid)
                        host.genParamSet("pool", p, "suspend-image-SR", sr.uuid)

                if xenrt.TEC().lookup("PAUSE_BEFORE_POOL", False, boolean=True):
                    xenrt.TEC().tc.pause("Pausing before creating pool(s)")

                # Add the slaves to the pools, they should all pick up the
                # relevant SRs and network config
                forceJoin = xenrt.TEC().lookup("POOL_JOIN_FORCE", False, boolean=True)
                totalSlaves = 0
                for p in self.pools:
                    master = xenrt.TEC().registry.hostGet(p["master"])
                    pool = xenrt.productLib(host=master).poolFactory(master.productVersion)(master)
                    if p["ssl"]:
                        pool.configureSSL()
                    slaves = filter(lambda x:x["pool"] == p["name"] \
                                     and not x["name"] == p["master"],
                                     self.hosts)
                    totalSlaves += len(slaves)
                    for s in slaves:
                        slave = xenrt.TEC().registry.hostGet(s["name"])
                        pool.addHost(slave, force=forceJoin)
                    xenrt.TEC().registry.poolPut(p["name"], pool)

                if totalSlaves > 0 and len(self.networksForPools) > 0:
                    # Allow 5 minutes for the slaves to create network objects etc CA-47814
                    
                    xenrt.sleep(300)

                # If we have a network topology definition then apply the
                # management/IP part of that to the slaves. First check them
                # have correctly inherited the VLANs/bonds
                for p in self.pools:
                    if self.networksForPools.has_key(p["name"]):
                        t = self.networksForPools[p["name"]]
                        slaves = filter(lambda x:x["pool"] == p["name"] \
                                         and not x["name"] == p["master"],
                                         self.hosts)
                        queue = InstallWorkQueue()
                        for s in slaves:
                            queue.add((s, t))
                        workers = []
                        for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                            w = SlaveManagementWorker(queue, name="SMWorker%02u" % (i))
                            workers.append(w)
                            w.start()
                        for w in workers:
                            w.join()
                        for w in workers:
                            if w.exception:
                                raise w.exception

                # Check all hosts are marked as enabled
                xenrt.TEC().logverbose("Checking all hosts are enabled")
                hostsToCheck = []
                hostsToCheck.extend(\
                    map(lambda h:xenrt.TEC().registry.hostGet(h["name"]),
                        self.hosts))
                deadline = xenrt.util.timenow() + 1200
                while True:
                    if len(hostsToCheck) == 0:
                        break
                    for h in hostsToCheck:
                        if h.isEnabled():
                            hostsToCheck.remove(h)
                    if xenrt.util.timenow() > deadline:
                        raise xenrt.XRTFailure(\
                            "Timed out waiting for hosts to be enabled: %s" %
                            (string.join(map(lambda x:x.getName(), hostsToCheck))))
                    xenrt.sleep(30, log=False)
                    
                if xenrt.TEC().lookup("OPTION_ENABLE_REDO_LOG", False, boolean=True):
                    for p in self.pools:
                        pool = xenrt.TEC().registry.poolGet(p["name"])
                        defaultsr = pool.master.minimalList("pool-list", "default-SR")[0]
                        pool.master.getCLIInstance().execute("pool-enable-redo-log", "sr-uuid=%s" % defaultsr)

            # Run pre job tests on all hosts
            for h in map(lambda i:xenrt.TEC().registry.hostGet(i["name"]), self.hosts):
                h.preJobTests()
            xenrt.GEC().preJobTestsDone = True

            if len(self.vms) > 0:
                queue = InstallWorkQueue()
                for v in self.vms:
                    if not (v.has_key("host") and v["host"] == "SHARED"):
                        queue.add(v)
                workers = []
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = GuestInstallWorker(queue, name="GWorker%02u" % (i))
                    workers.append(w)
                    w.start()
                for w in workers:
                    w.join()
                for w in workers:
                    if w.exception:
                        raise w.exception
            if len(sharedGuestWorkers) > 0:
                for w in sharedGuestWorkers:
                    w.join()
                for w in sharedGuestWorkers:
                    if w.exception:
                        raise w.exception
            
            if not nohostprepare:
                xenrt.TEC().logverbose("Controller configurations: %s %s" % 
                                       (self.controllersForPools, self.controllersForHosts)) 
                for p in self.controllersForPools:
                    controller = xenrt.TEC().registry.guestGet(self.controllersForPools[p])
                    pool = xenrt.TEC().registry.poolGet(p)
                    pool.associateDVS(controller.getDVSCWebServices())
                for h in self.controllersForHosts:
                    controller = xenrt.TEC().registry.guestGet(self.controllersForHosts[h])
                    host = xenrt.TEC().registry.hostGet(h)
                    host.associateDVS(controller.getDVSCWebServices())

                if self.cloudSpec:
                    xenrt.lib.cloud.doDeploy(self.cloudSpec)

            if len(self.templates) > 0:
                queue = InstallWorkQueue()
                for t in self.templates:
                    queue.add(t)
                workers = []
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = TemplateInstallWorker(queue, name="TWorker%02u" % (i))
                    workers.append(w)
                    w.start()
                for w in workers:
                    w.join()
                for w in workers:
                    if w.exception:
                        raise w.exception
            if len(self.instances) > 0:
                queue = InstallWorkQueue()
                for i in self.instances:
                    queue.add(i)
                workers = []
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = InstanceInstallWorker(queue, name="IWorker%02u" % (i))
                    workers.append(w)
                    w.start()
                for w in workers:
                    w.join()
                for w in workers:
                    if w.exception:        
                        raise w.exception
            if len(self.blueprints) > 0:
                queue = InstallWorkQueue()
                for b in self.blueprints:
                    queue.add(b)
                workers = []
                for i in range(max(int(xenrt.TEC().lookup("PREPARE_WORKERS", "4")), 4)):
                    w = BlueprintInstallWorker(queue, name="BPWorker%02u" % (i))
                    workers.append(w)
                    w.start()
                for w in workers:
                    w.join()
                for w in workers:
                    if w.exception:
                        raise w.exception

        except Exception, e:
            sys.stderr.write(str(e))
            traceback.print_exc(file=sys.stderr)
            if xenrt.TEC().lookup("AUTO_BUG_FILE", False, boolean=True):
                # File a Jira Bug
                try:
                    jl = xenrt.jiralink.getJiraLink()
                    jl.processPrepare(xenrt.TEC(),str(e))
                except Exception, jiraE:
                    xenrt.GEC().logverbose("Jira Link Exception: %s" % (jiraE),
                                           pref='WARNING')

            raise

#        self.__createDeploymentRecord()

    def __createDeploymentRecord(self):
        deploymentRec = {}
        # Process Hosts - first get a list of unique host objects
        deploymentRec['hosts'] = []
        hostObjList = list(set(map(lambda x:xenrt.TEC().registry.hostGet(x), xenrt.TEC().registry.hostList())))
        for host in hostObjList:
            deploymentRec['hosts'].append( { 'name': host.getName(), 'mgmt_ipv4': host.getIP(), 'root_user': 'root', 'root_password': host.password } )

        with open(os.path.join(xenrt.TEC().getLogdir(), 'deployment.json'), 'w') as fh:
            json.dump(deploymentRec, fh)

class InstallWorkQueue(object):
    """Queue of install work items to perform."""
    def __init__(self):
        self.items = []
        self.mylock = threading.Lock()

    def consume(self):
        self.mylock.acquire()
        reply = None
        try:
            if len(self.items) > 0:
                reply = self.items.pop()
        finally:
            self.mylock.release()
        return reply

    def add(self, item):
        self.mylock.acquire()
        try:
            self.items.append(item)
        finally:
            self.mylock.release()

class _InstallWorker(xenrt.XRTThread):
    """Worker thread for parallel host or guest installs (parent class)"""
    def __init__(self, queue, name=None):
        self.queue = queue
        self.exception = None
        xenrt.XRTThread.__init__(self, name=name)

    def doWork(self, work):
        pass

    def run(self):
        xenrt.TEC().logverbose("Install worker '%s' starting..." %
                               (self.getName()))
        while True:
            work = self.queue.consume()
            if not work:
                break
            try:
                self.doWork(work)
            except xenrt.XRTException, e:
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
                self.exception = e
                self.exception_extended = sys.exc_info()
                xenrt.TEC().logverbose(str(e), pref='REASON')
                if e.data:
                    xenrt.TEC().logverbose(str(e.data)[:1024], pref='REASONPLUS')
            except Exception, e:
                reason = "Unhandled exception %s" % (str(e))
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
                self.exception = e
                self.exception_extended = sys.exc_info()
                xenrt.TEC().logverbose(reason, pref='REASON')
                                        
class HostInstallWorker(_InstallWorker):
    """Worker thread for parallel host installs"""
    def doWork(self, work):
        if work.has_key("id") and not xenrt.TEC().lookup("RESOURCE_HOST_%s" % (work["id"]), False):
            raise xenrt.XRTError("We require RESOURCE_HOST_%s but it has not been specified." % (work["id"]))
        initialVersion = xenrt.TEC().lookup("INITIAL_INSTALL_VERSION", None)
        versionPath = xenrt.TEC().lookup("INITIAL_VERSION_PATH", None)
        specProductType = "xenserver"
        specProductVersion = None
        specVersion = None
        defaultHost = False
        if work.has_key("productType"):
            specProductType = work["productType"]
        if work.has_key("productVersion"):
            specProductVersion = work["productVersion"]
        if work.has_key("version"):
            specVersion = work["version"]
        if work.has_key("default"):
            defaultHost = work['default']
            del work['default']

        hostname = xenrt.TEC().lookup("RESOURCE_HOST_%s" % work.get("id", "0"))

        logid = xenrt.GEC().dbconnect.jobLogItem("Installing host %s of type %s" % (hostname, specProductType))
        try:
            if specProductType == "xenserver":
                if versionPath and not specProductVersion and not specVersion:
                    # Install the specified sequence of versions and upgrades/updates
                    if work.has_key("version"):
                        del work["version"]
                    if work.has_key("productVersion"):
                        del work["productVersion"]
                    if work.has_key("productType"):
                        del work["productType"]
                    work["versionPath"] = versionPath
                    xenrt.TEC().logverbose("Installing using version path %s" %
                                           (versionPath))
                    host = xenrt.lib.xenserver.host.createHostViaVersionPath(**work)
                elif initialVersion and not specProductVersion and not specVersion:
                    # Install this version and upgrade afterwards
                    inputdir = xenrt.TEC().lookup("PRODUCT_INPUTDIR_%s" %
                                                  (initialVersion.upper()), None)
                    if not inputdir:
                        inputdir = xenrt.TEC().lookup("PIDIR_%s" %
                                                      (initialVersion.upper()), None)
                    if not inputdir:
                        raise xenrt.XRTError("No product input directory set for %s" %
                                             (initialVersion))
                    work["version"] = inputdir
                    work["productVersion"] = initialVersion
                    xenrt.TEC().logverbose("Installing using initial version %s" %
                                           (initialVersion))
                    license = None
                    if work.has_key("license"):
                        license = work["license"]
                        del work["license"]
                        xenrt.TEC().logverbose("Ignoring license information for previous version install")
                    host = xenrt.lib.xenserver.host.createHost(**work)
                    xenrt.TEC().setInputDir(None)
                    xenrt.TEC().logverbose("Upgrading to current version")
                    host = host.upgrade()
                    if license:
                        xenrt.TEC().logverbose("Licensing upgraded host...")
                        if type(license) == type(""):
                            host.license(sku=license)
                        else:
                            host.license()
                else:
                    # Normal install of the default or host-specified version
                    xenrt.TEC().setInputDir(None)
                    host = xenrt.lib.xenserver.host.createHost(**work)
            elif specProductType == "nativelinux":
                if specProductType is None:
                    raise xenrt.XRTError("We require a ProductVersion specifying the native Linux host type.")
                work["noisos"] = True
                host = xenrt.lib.native.createHost(**work)
            elif specProductType == "nativewindows":
                if specProductType is None:
                    raise xenrt.XRTError("We require a ProductVersion specifying the native Windows host type.")
                work["noisos"] = True
                host = xenrt.lib.nativewindows.createHost(**work)
            elif specProductType == "kvm":
                work["productVersion"] = specProductVersion or xenrt.TEC().lookup("PRODUCT_VERSION", None)
                host = xenrt.lib.kvm.createHost(**work)
            elif specProductType == "esx":
                # Ideally, we would have set the PRODUCT_VERSION in handleHostNode, but for XenServer we rely on work["productVersion"] remaining None even when PRODUCT_VERSION being set
                work["productVersion"] = specProductVersion or xenrt.TEC().lookup("PRODUCT_VERSION", None)
                host = xenrt.lib.esx.createHost(**work)
            elif specProductType == "hyperv":
                work["noisos"] = True
                host = xenrt.lib.hyperv.createHost(**work)
            elif specProductType == "oss":
                work["noisos"] = True
                host = xenrt.lib.oss.createHost(**work)
            else:
                raise xenrt.XRTError("Unknown productType: %s" % (specProductType))

            if defaultHost:
                xenrt.TEC().registry.hostPut("RESOURCE_HOST_DEFAULT", host)
            xenrt.GEC().dbconnect.jobLogItem("Installed host %s" % (hostname), linked=logid, completes=True)
        except Exception, e:
            xenrt.GEC().dbconnect.jobLogItem("Failed to install host %s - %s" % (hostname, str(e)), linked=logid, completes=True, iserror=True)
            raise
            

class GuestInstallWorker(_InstallWorker):
    """Worker thread for parallel guest installs"""
    def doWork(self, work):
        if work.has_key("filename"):
            logid = xenrt.GEC().dbconnect.jobLogItem("Importing VM from %s" % (work['filename']))
            try:
                xenrt.productLib(hostname=work["host"]).guest.createVMFromFile(**work)
                xenrt.GEC().dbconnect.jobLogItem("Completed import VM from %s" % (work['filename']), completes=True, linked=logid)
            except Exception, e:
                xenrt.GEC().dbconnect.jobLogItem("Failed to import VM from %s (%s)" % (work['filename'], str(e)), completes=True, linked=logid, iserror=True)
                raise
        else:
            logid = xenrt.GEC().dbconnect.jobLogItem("Installing VM of type %s" % (work.get("distro", "unknown")))
            try:
                if xenrt.TEC().lookup("DEFAULT_VIFS", False, boolean=True) and (not "vifs" in work or not work['vifs']):
                    host = work["host"]
                    if not isinstance(host, xenrt.GenericHost):
                        host = xenrt.TEC().registry.hostGet(host)
                    work['vifs'] = host.guestFactory().DEFAULT
                xenrt.productLib(hostname=work["host"]).guest.createVM(**work)
                xenrt.GEC().dbconnect.jobLogItem("Installed VM of type %s" % (work.get("distro", "unknown")), completes=True, linked=logid)
            except Exception, e:
                xenrt.GEC().dbconnect.jobLogItem("Failed to install VM of type %s (%s)" % (work.get("distro", "unknown"), str(e)), completes=True, linked=logid, iserror=True)
                raise

class SlaveManagementWorker(_InstallWorker):
    """Worker thread for parallel slave management interface reconfigures"""
    def doWork(self, work):
        s = work[0] # Slave machine
        t = work[1] # Network topology
        slave = xenrt.TEC().registry.hostGet(s["name"])
        slave.checkNetworkTopology(t,
                                   ignoremanagement=True,
                                   ignorestorage=True)
        slave.addIPConfigToNetworkTopology(t)
        slave.checkNetworkTopology(t)

class TemplateInstallWorker(_InstallWorker):
    """Worker thread for parallel template installs"""
    def doWork(self, work):
        toolstack = xenrt.TEC().registry.toolstackGetDefault()
        toolstack.createOSTemplate(**work)

class InstanceInstallWorker(_InstallWorker):
    """Worker thread for parallel instance installs"""
    def doWork(self, work):
        toolstack = xenrt.TEC().registry.toolstackGetDefault()
        toolstack.createInstance(**work) 

class BlueprintInstallWorker(_InstallWorker):
    """Worker thread for parallel blueprint installs"""
    def doWork(self, work):
        # TODO: Generalise for other hypervisors + multiple pool scenarios etc
        sxp = xenrt.lib.scalextreme.sxprocess.SXProcess.getByName(work["name"], work["version"], work["deploymentProfileTemplateName"])

        provider = xenrt.TEC().registry.sxProviderGetDefault()
        template = xenrt.TEC().registry.guestGet(work["template"])
        host = template.getHost()

        sxp.deploy(provider['providerId'], host, template.getUUID(), template.password)

