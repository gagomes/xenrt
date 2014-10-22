from mock import patch, Mock, PropertyMock
import xenrt
from testing import XenRTUnitTestCase

import copy
import re
import pprint
import IPy


nextIP = None

class TestMarvinConfig(XenRTUnitTestCase):

    DEFAULT_VARS = {"NETWORK_CONFIG/DEFAULT/NAMESERVERS": "10.0.0.2",
                    "NETWORK_CONFIG/DEFAULT/SUBNETMASK": "255.255.255.0",
                    "NETWORK_CONFIG/DEFAULT/GATEWAY": "10.0.0.1",
                    "NETWORK_CONFIG/SECONDARY/VLAN" : 800,
                    "NETWORK_CONFIG/SECONDARY/SUBNETMASK" : "255.255.255.128",
                    "NETWORK_CONFIG/SECONDARY/GATEWAY" : "10.1.0.1",
                    "NETWORK_CONFIG/SECONDARY/ADDRESS" : "10.1.0.2",
                    "XENRT_SERVER_ADDRESS": "10.0.0.2",
                    "CLOUDINPUTDIR": "http://repo/location",
                    "ROOT_PASSWORD": "xenroot",
                    "AD_CONFIG": {"ADMIN_USER": "Administrator", "ADMIN_PASSWORD": "xenroot01T", "DOMAIN_NAME": "XSQA", "DOMAIN": "ad.qa.xs.citrite.net", "DNS": "10.220.254.115", "DC_ADDRESS": "10.220.254.115", "DC_DISTRO": "ws12-x64"},
                    "VCENTER": {"ADDRESS": "10.2.0.1", "USERNAME": "Administrator@vsphere.local", "PASSWORD": "xenroot01T!"},
                    "VCENTER/ADDRESS": "10.2.0.1"
                    }

    def addTC(self, cls):
        self.tcs.append((cls.__name__, cls.IN, cls.OUT, cls.EXTRAVARS))

    def test_marvin_config_generator(self):
        self.tcs = []
        self.addTC(TC1)
        self.addTC(TC2)
        self.addTC(TC3)
        self.addTC(TC4)
        self.addTC(TC5)
        self.addTC(TC6)
        self.addTC(TC7)
        self.run_for_many(self.tcs, self.__test_marvin_config_generator)

    @patch("xenrt.lib.netscaler.NetScaler.setupNetScalerVpx")
    @patch("xenrt.ExternalSMBShare")
    @patch("xenrt.ExternalNFSShare")
    @patch("xenrt.command")
    @patch("xenrt.TempDirectory")
    @patch("xenrt.StaticIP4Addr.getIPRange")
    @patch("xenrt.PrivateVLAN.getVLANRange")
    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def __test_marvin_config_generator(self, data, tec, gec, pvlan, ip, td, cmd, nfs, smb, ns):
        import xenrt.lib.cloud.marvindeploy

        ip.side_effect = self.__getIPRange
        pvlan.side_effect = self.__getVLANRange
        self.dummytec = DummyTEC(self)
        dummyNfs = Mock()
        dummyNfs.getMount.return_value = "nfsserver:/path"
        nfs.return_value = dummyNfs
        dummySmb = Mock()
        dummySmb.getMount.return_value = "smbserver:/path"
        smb.return_value = dummySmb
        dummyNs = Mock()
        dummyNs.managementIp = "10.3.1.1"
        dummyNs.subnetIp.return_value = "10.3.1.2"
        ns.return_value = dummyNs
        tec.return_value = self.dummytec
        gec.return_value = self.dummytec
        (tcname, indata, outdata, extravars) = data
        self.extravars = extravars
        unit = xenrt.lib.cloud.marvindeploy.MarvinDeployer("1.1.1.1", Mock(), "root", "xenroot", None)
        cfg = copy.deepcopy(indata)

        marvin = Mock()

        deployer = xenrt.lib.cloud.deploy.DeployerPlugin(marvin)
        unit._processConfigElement(cfg, 'config', deployer)
        expected = self.removeXRTValues(outdata)
        actual = self.removeXRTValues(cfg)
        try:
            self.assertEqual(expected, actual)
        except:
            print "Input Data for test %s" % tcname
            pprint.pprint(indata)
            print "Expected"
            pprint.pprint(expected)
            print "Actual"
            pprint.pprint(actual)
            raise

    def _lookup(self, var, default="BADVALUE", boolean=False):
        values = {}

        if isinstance(var, list):
            var = "/".join(var)

        values.update(self.DEFAULT_VARS)
        values.update(self.extravars)
        if not values.has_key(var):
            if default == "BADVALUE":
                raise Exception("No default value specified for %s" % var)
            return default
        else:
            if boolean:
                if values[var][0].lower() in ("y", "t", "1"):
                    return True
                else:
                    return False
            else:
                return values[var]

    def removeXRTValues(self, value):
        if isinstance(value, dict):
            ret = {}
            for k in value.keys():
                if not k.startswith("XRT_"):
                    ret[k] = self.removeXRTValues(value[k])
        elif isinstance(value, list):
            ret = [self.removeXRTValues(x) for x in value]
        else:
            ret = value
        return ret

    @classmethod
    def __getVLANRange(cls, size):
        vlans = []
        for i in range(size):
            m = Mock()
            m.getID.return_value = 3000+i
            vlans.append(m)
        return vlans

    @classmethod
    def __getIPRange(cls, size, network=None):
        addrs = []
        global nextIP
        for i in range(size):
            m = Mock()
            m.getAddr.return_value = str(IPy.IP(IPy.IP("10.1.0.1").int() + i))
            addrs.append(m)
        return addrs

class DummyTEC(object):
    def __init__(self, parent):
        self.parent = parent
        self.registry = DummyRegistry()

    def logverbose(self, msg):
        pass

    def lookup(self, var, default="BADVALUE", boolean=False):
        return self.parent._lookup(var, default, boolean=False)

    def getFile(self, *files):
        return "/path/to/file"

    @property
    def config(self):
        return self

class DummyRegistry(object):
    def __init__(self):
        self.objs = {}
    
    def dump(self):
        pass

    def hostGet(self, h):
        index = int(re.match("RESOURCE_HOST_(\d+)", h).group(1))
        m = Mock()
        m.getIP.return_value = str(IPy.IP(IPy.IP("10.0.0.3").int() + index))
        m.getFQDN.return_value = "h%d.domain" % index
        return m

    def guestGet(self, g):
        g = Mock()
        g.createLinuxNfsShare.return_value = "guest:/path"
        return g

    def objPut(self, objType, tag, obj):
        self.objs["%s-%s" % (objType, tag)] = obj

    def objGet(self, objType, tag):
        return self.objs["%s-%s" % (objType, tag)]
        

class BaseTC(object):
    EXTRAVARS = {}

class TC1(BaseTC):
    """Test that Hyper-V zones use SMB storage"""

    IN = {'zones': [{'guestcidraddress': '192.168.200.0/24',
             'ipranges': [{'XRT_GuestIPRangeSize': 10, 'XRT_VlanName': 'NSEC'}],
             'XRT_ZoneNetwork': 'NSEC',
             'networktype': 'Advanced',
             'physical_networks': [{'XRT_VLANRangeSize': 10,
                                     'isolationmethods': ['VLAN'],
                                     'name': 'AdvPhyNetwork',
                                     'providers': [{'broadcastdomainrange': 'ZONE',
                                                     'name': 'VirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'VpcVirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'InternalLbVm'}],
                                     'traffictypes': [{'typ': 'Guest'},
                                                       {'typ': 'Management'},
                                                       {'typ': 'Public'}]}],
             'pods': [{'XRT_PodIPRangeSize': 10,
                        'clusters': [{'XRT_Hosts': 1,
                                       'XRT_HyperVHostIds': '0',
                                       'hypervisor': 'hyperv'}]}]}]}

    OUT = {'zones': [{'dns1': '10.1.0.2',
         'domain': 'nsec-xenrtcloud',
         'guestcidraddress': '192.168.200.0/24',
         'internaldns1': '10.0.0.2',
         'ipranges': [{'XRT_GuestIPRangeSize': 10,
                        'endip': '10.1.0.10',
                        'gateway': '10.1.0.1',
                        'netmask': '255.255.255.128',
                        'startip': '10.1.0.1',
                        'vlan': 800}],
         'name': 'XenRT-Zone-0',
         'networktype': 'Advanced',
         'physical_networks': [{'XRT_VLANRangeSize': 10,
                                 'broadcastdomainrange': 'Zone',
                                 'isolationmethods': ['VLAN'],
                                 'name': 'AdvPhyNetwork',
                                 'providers': [{'broadcastdomainrange': 'ZONE',
                                                 'name': 'VirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'VpcVirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'InternalLbVm'}],
                                 'traffictypes': [{'typ': 'Guest'},
                                                   {'typ': 'Management'},
                                                   {'typ': 'Public'}],
                                 'vlan': '3000-3009'}],
         'pods': [{'XRT_PodIPRangeSize': 10,
                    'clusters': [{'XRT_Hosts': 1,
                                   'XRT_HyperVHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'CloudManaged',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://h0.domain',
                                              'username': 'root'}],
                                   'hypervisor': 'hyperv',
                                   'primaryStorages': [{'details': {'user': 'Administrator',
                                                                    'password': 'xenroot01T',
                                                                    'domain': 'XSQA'},
                                                        'name': 'XenRT-Zone-0-Pod-0-Cluster-0-Primary-Store-0',
                                                        'url': 'cifs://h0.domain/storage/primary'}]}],
                    'endip': '10.1.0.10',
                    'gateway': '10.0.0.1',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.255.0',
                    'startip': '10.1.0.1'}],
         'secondaryStorages': [{'XRT_SMBHostId': '0',
                                'details': {'domain': 'XSQA',
                                            'password': 'xenroot01T',
                                            'user': 'Administrator'},
                                'provider': 'SMB',
                                'url': 'cifs://10.0.0.3/storage/secondary'}]}]} 

class TC2(BaseTC):
    """Test that KVM zones use NFS storage"""

    IN = {'zones': [{'guestcidraddress': '192.168.200.0/24',
             'ipranges': [{'XRT_GuestIPRangeSize': 10}],
             'networktype': 'Advanced',
             'physical_networks': [{'XRT_VLANRangeSize': 10,
                                     'isolationmethods': ['VLAN'],
                                     'name': 'AdvPhyNetwork',
                                     'providers': [{'broadcastdomainrange': 'ZONE',
                                                     'name': 'VirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'VpcVirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'InternalLbVm'}],
                                     'traffictypes': [{'typ': 'Guest'},
                                                       {'typ': 'Management'},
                                                       {'typ': 'Public'}]}],
             'pods': [{'XRT_PodIPRangeSize': 10,
                        'clusters': [{'XRT_Hosts': 1,
                                       'XRT_KVMHostIds': '0',
                                       'hypervisor': 'KVM'}]}]}]}

    OUT = {'zones': [{'dns1': '10.0.0.2',
         'domain': 'xenrtcloud',
         'guestcidraddress': '192.168.200.0/24',
         'internaldns1': '10.0.0.2',
         'ipranges': [{'XRT_GuestIPRangeSize': 10,
                        'endip': '10.1.0.10',
                        'gateway': '10.0.0.1',
                        'netmask': '255.255.255.0',
                        'startip': '10.1.0.1'}],
         'name': 'XenRT-Zone-0',
         'networktype': 'Advanced',
         'physical_networks': [{'XRT_VLANRangeSize': 10,
                                 'broadcastdomainrange': 'Zone',
                                 'isolationmethods': ['VLAN'],
                                 'name': 'AdvPhyNetwork',
                                 'providers': [{'broadcastdomainrange': 'ZONE',
                                                 'name': 'VirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'VpcVirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'InternalLbVm'}],
                                 'traffictypes': [{'typ': 'Guest'},
                                                   {'typ': 'Management'},
                                                   {'typ': 'Public'}],
                                 'vlan': '3000-3009'}],
         'pods': [{'XRT_PodIPRangeSize': 10,
                    'clusters': [{'XRT_Hosts': 1,
                                   'XRT_KVMHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'CloudManaged',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://10.0.0.3',
                                              'username': 'root'}],
                                   'hypervisor': 'KVM',
                                   'primaryStorages': [{'name': 'XenRT-Zone-0-Pod-0-Cluster-0-Primary-Store-0',
                                                        'url': 'nfs://nfsserver/path'}]}],
                    'endip': '10.1.0.10',
                    'gateway': '10.0.0.1',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.255.0',
                    'startip': '10.1.0.1'}],
         'secondaryStorages': [{'provider': 'NFS',
                                'url': 'nfs://nfsserver/path'}]}]} 


class TC3(BaseTC):
    """Test that KVM zones can use guest-based NFS primary storage"""

    IN = {'zones': [{'networktype': 'Basic',
             'physical_networks': [{'name': 'BasicPhyNetwork'}],
             'pods': [{'XRT_PodIPRangeSize': 10,
                        'clusters': [{'XRT_Hosts': 1,
                                       'XRT_KVMHostIds': '0',
                                       'hypervisor': 'KVM',
                                       'primaryStorages': [{'XRT_Guest_NFS': 'PriStoreNFS'}]}],
                        'guestIpRanges': [{'XRT_GuestIPRangeSize': 15}]}]}]}

    OUT = {'zones': [{'dns1': '10.0.0.2',
            'internaldns1': '10.0.0.2',
            'domain': 'xenrtcloud',
            'name': 'XenRT-Zone-0',
            'networktype': 'Basic',
            'physical_networks': [{'broadcastdomainrange': 'Zone',
                                   'name': 'BasicPhyNetwork',
                                   'providers': [{'broadcastdomainrange': 'ZONE',
                                                  'name': 'VirtualRouter'},
                                                 {'broadcastdomainrange': 'Pod',
                                                  'name': 'SecurityGroupProvider'}],
                                   'traffictypes': [{'typ': 'Guest'},
                                                    {'typ': 'Management'}],
                                   'vlan': None}],
            'pods': [{'clusters': [{'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                    'clustertype': 'CloudManaged',
                                    'hosts': [{'password': 'xenroot',
                                               'url': 'http://10.0.0.3',
                                               'username': 'root'}],
                                    'hypervisor': 'KVM',
                                    'primaryStorages': [{'name': 'XenRT-Zone-0-Pod-0-Cluster-0-Primary-Store-0',
                                                         'url': 'nfs://guest/path'}]}],
                      'endip': '10.1.0.10',
                      'gateway': '10.0.0.1',
                      'guestIpRanges': [{'endip': '10.1.0.15',
                                         'gateway': '10.0.0.1',
                                         'netmask': '255.255.255.0',
                                         'startip': '10.1.0.1'}],
                      'name': 'XenRT-Zone-0-Pod-0',
                      'netmask': '255.255.255.0',
                      'startip': '10.1.0.1'}],
            'secondaryStorages': [{'provider': 'NFS',
                                   'url': 'nfs://nfsserver/path'}]}]}

class TC4(BaseTC):
    """Test that KVM zones can use guest-based NFS secondary storage"""

    IN = {'zones': [{'networktype': 'Basic',
             'physical_networks': [{'name': 'BasicPhyNetwork'}],
             'pods': [{'XRT_PodIPRangeSize': 10,
                        'clusters': [{'XRT_Hosts': 1,
                                       'XRT_KVMHostIds': '0',
                                       'hypervisor': 'KVM'}],
                        'guestIpRanges': [{'XRT_GuestIPRangeSize': 15}]}],
             'secondaryStorages': [{'XRT_Guest_NFS': 'PriStoreNFS'}]}]}

    OUT = {'zones': [{'dns1': '10.0.0.2',
            'internaldns1': '10.0.0.2',
            'domain': 'xenrtcloud',
            'name': 'XenRT-Zone-0',
            'networktype': 'Basic',
            'physical_networks': [{'broadcastdomainrange': 'Zone',
                                   'name': 'BasicPhyNetwork',
                                   'providers': [{'broadcastdomainrange': 'ZONE',
                                                  'name': 'VirtualRouter'},
                                                 {'broadcastdomainrange': 'Pod',
                                                  'name': 'SecurityGroupProvider'}],
                                   'traffictypes': [{'typ': 'Guest'},
                                                    {'typ': 'Management'}],
                                   'vlan': None}],
            'pods': [{'clusters': [{'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                    'clustertype': 'CloudManaged',
                                    'hosts': [{'password': 'xenroot',
                                               'url': 'http://10.0.0.3',
                                               'username': 'root'}],
                                    'hypervisor': 'KVM',
                                    'primaryStorages': [{'name': 'XenRT-Zone-0-Pod-0-Cluster-0-Primary-Store-0',
                                                         'url': 'nfs://nfsserver/path'}]}],
                      'endip': '10.1.0.10',
                      'gateway': '10.0.0.1',
                      'guestIpRanges': [{'endip': '10.1.0.15',
                                         'gateway': '10.0.0.1',
                                         'netmask': '255.255.255.0',
                                         'startip': '10.1.0.1'}],
                      'name': 'XenRT-Zone-0-Pod-0',
                      'netmask': '255.255.255.0',
                      'startip': '10.1.0.1'}],
            'secondaryStorages': [{'provider': 'NFS',
                                   'url': 'nfs://guest/path'}]}]}

class TC5(BaseTC):
    """Test that Hyper-V zones use SMB storage from the host when EXTERNAL_SMB is set"""

    EXTRAVARS = {"EXTERNAL_SMB": "yes"}

    IN = {'zones': [{'guestcidraddress': '192.168.200.0/24',
             'ipranges': [{'XRT_GuestIPRangeSize': 10}],
             'networktype': 'Advanced',
             'physical_networks': [{'XRT_VLANRangeSize': 10,
                                     'isolationmethods': ['VLAN'],
                                     'name': 'AdvPhyNetwork',
                                     'providers': [{'broadcastdomainrange': 'ZONE',
                                                     'name': 'VirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'VpcVirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'InternalLbVm'}],
                                     'traffictypes': [{'typ': 'Guest'},
                                                       {'typ': 'Management'},
                                                       {'typ': 'Public'}]}],
             'pods': [{'XRT_PodIPRangeSize': 10,
                        'clusters': [{'XRT_Hosts': 1,
                                       'XRT_HyperVHostIds': '0',
                                       'hypervisor': 'hyperv'}]}]}]}

    OUT = {'zones': [{'dns1': '10.0.0.2',
         'domain': 'xenrtcloud',
         'guestcidraddress': '192.168.200.0/24',
         'internaldns1': '10.0.0.2',
         'ipranges': [{'XRT_GuestIPRangeSize': 10,
                        'endip': '10.1.0.10',
                        'gateway': '10.0.0.1',
                        'netmask': '255.255.255.0',
                        'startip': '10.1.0.1'}],
         'name': 'XenRT-Zone-0',
         'networktype': 'Advanced',
         'physical_networks': [{'XRT_VLANRangeSize': 10,
                                 'broadcastdomainrange': 'Zone',
                                 'isolationmethods': ['VLAN'],
                                 'name': 'AdvPhyNetwork',
                                 'providers': [{'broadcastdomainrange': 'ZONE',
                                                 'name': 'VirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'VpcVirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'InternalLbVm'}],
                                 'traffictypes': [{'typ': 'Guest'},
                                                   {'typ': 'Management'},
                                                   {'typ': 'Public'}],
                                 'vlan': '3000-3009'}],
         'pods': [{'XRT_PodIPRangeSize': 10,
                    'clusters': [{'XRT_Hosts': 1,
                                   'XRT_HyperVHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'CloudManaged',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://h0.domain',
                                              'username': 'root'}],
                                   'hypervisor': 'hyperv',
                                   'primaryStorages': [{'details': {'user': 'Administrator',
                                                                    'password': 'xenroot01T',
                                                                    'domain': 'XSQA'},
                                                        'name': 'XenRT-Zone-0-Pod-0-Cluster-0-Primary-Store-0',
                                                        'url': 'cifs://h0.domain/storage/primary'}]}],
                    'endip': '10.1.0.10',
                    'gateway': '10.0.0.1',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.255.0',
                    'startip': '10.1.0.1'}],
         'secondaryStorages': [{'XRT_SMBHostId': '0',
                                'details': {'domain': 'XSQA',
                                            'password': 'xenroot01T',
                                            'user': 'Administrator'},
                                'provider': 'SMB',
                                'url': 'cifs://smbserver/path'}]}]} 

class TC6(BaseTC):
    """Test VMWare zones populate pods and clusters with correct info"""

    IN = {'zones': [{'guestcidraddress': '192.168.200.0/24',
             'ipranges': [{'XRT_GuestIPRangeSize': 10}],
             'networktype': 'Advanced',
             'XRT_VMWareDC': 'vmwd1',
             'physical_networks': [{'XRT_VLANRangeSize': 10,
                                     'isolationmethods': ['VLAN'],
                                     'name': 'AdvPhyNetwork',
                                     'providers': [{'broadcastdomainrange': 'ZONE',
                                                     'name': 'VirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'VpcVirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'InternalLbVm'}],
                                     'traffictypes': [{'typ': 'Guest'},
                                                       {'typ': 'Management'},
                                                       {'typ': 'Public'}]}],
             'pods': [{'XRT_PodIPRangeSize': 10,
                        'XRT_VMWareDC': 'vmwd1',
                        'clusters': [{'XRT_Hosts': 1,
                                       'XRT_VMWareDC': 'vmwd1',
                                       'XRT_VMWareCluster': 'vmwc1',
                                       'XRT_VMWareHostIds': '0',
                                       'hypervisor': 'vmware'}]}]}]}

    OUT = {'zones': [{'dns1': '10.0.0.2',
         'domain': 'xenrtcloud',
         'guestcidraddress': '192.168.200.0/24',
         'internaldns1': '10.0.0.2',
         'ipranges': [{'XRT_GuestIPRangeSize': 10,
                        'endip': '10.1.0.10',
                        'gateway': '10.0.0.1',
                        'netmask': '255.255.255.0',
                        'startip': '10.1.0.1'}],
         'name': 'XenRT-Zone-0',
         'networktype': 'Advanced',
         'physical_networks': [{'XRT_VLANRangeSize': 10,
                                 'broadcastdomainrange': 'Zone',
                                 'isolationmethods': ['VLAN'],
                                 'name': 'AdvPhyNetwork',
                                 'providers': [{'broadcastdomainrange': 'ZONE',
                                                 'name': 'VirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'VpcVirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'InternalLbVm'}],
                                 'traffictypes': [{'typ': 'Guest'},
                                                   {'typ': 'Management'},
                                                   {'typ': 'Public'}],
                                 'vlan': '3000-3009'}],
         'pods': [{'XRT_PodIPRangeSize': 10,
                    'vmwaredc': {'name': 'vmwd1',
                                 'vcenter': '10.2.0.1',
                                 'username': 'Administrator@vsphere.local',
                                 'password': 'xenroot01T!'},
                    'clusters': [{'XRT_Hosts': 1,
                                   'XRT_VMWareHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'ExternalManaged',
                                   'url': 'http://10.2.0.1/vmwd1/vmwc1',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://10.0.0.3',
                                              'username': 'root'}],
                                   'hypervisor': 'vmware',
                                   'primaryStorages': [{'name': 'XenRT-Zone-0-Pod-0-Cluster-0-Primary-Store-0',
                                                        'url': 'nfs://nfsserver/path'}]}],
                    'endip': '10.1.0.10',
                    'gateway': '10.0.0.1',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.255.0',
                    'startip': '10.1.0.1'}],
         'secondaryStorages': [{'provider': 'NFS',
                                'url': 'nfs://nfsserver/path'}]}]} 

class TC7(BaseTC):
    """Test KVM zones with a Netscaler"""

    IN = {'zones': [{
             'ipranges': [{'XRT_GuestIPRangeSize': 10}],
             'networktype': 'Basic',
             'physical_networks': [{ 'name': 'test-network',
                                     'providers': [{'broadcastdomainrange': 'ZONE',
                                                     'name': 'VirtualRouter'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'SecurityGroupProvider'},
                                                    {'broadcastdomainrange': 'ZONE',
                                                     'name': 'Netscaler',
                                                     'XRT_NetscalerVM': 'NetscalerVPX',
                                                     'XRT_NetscalerNetworks': ["NSEC", "NPRI"]}],
                                     'traffictypes': [{'typ': 'Guest'},
                                                       {'typ': 'Management'},
                                                       {'typ': 'Public'}]}],
             'pods': [{'XRT_PodIPRangeSize': 10,
                       "XRT_NetscalerGateway": "NetscalerVPX",
                       "guestIpRanges": [
                         { "XRT_GuestIPRangeSize": 20, 
                           "XRT_NetscalerGateway": "NetscalerVPX"
                         }
                         ],
                        'clusters': [{'XRT_Hosts': 1,
                                       'XRT_KVMHostIds': '0',
                                       'hypervisor': 'KVM'}]}]}]}

    OUT = {'zones': [{'dns1': '10.0.0.2',
         'domain': 'xenrtcloud',
         'internaldns1': '10.0.0.2',
         'ipranges': [{'XRT_GuestIPRangeSize': 10,
                        'endip': '10.1.0.10',
                        'gateway': '10.0.0.1',
                        'netmask': '255.255.255.0',
                        'startip': '10.1.0.1'}],
         'name': 'XenRT-Zone-0',
         'networktype': 'Basic',
         'physical_networks': [{ 'broadcastdomainrange': 'Zone',
                                 'name': 'test-network',
                                 'providers': [{'broadcastdomainrange': 'ZONE',
                                                 'name': 'VirtualRouter'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'SecurityGroupProvider'},
                                                {'broadcastdomainrange': 'ZONE',
                                                 'name': 'Netscaler',
                                                 'devices': [
                                                   {"username": "nsroot",
                                                    "publicinterface": "1/1",
                                                    "hostname": "10.3.1.1",
                                                    "privateinterface": "1/2",
                                                    "lbdevicecapacity": "50",
                                                    "networkdevicetype": "NetscalerVPXLoadBalancer",
                                                    "lbdevicededicated": "false",
                                                    "password": "nsroot",
                                                    "numretries": "2"}
                                                 ]}],
                                 'traffictypes': [{'typ': 'Guest'},
                                                   {'typ': 'Management'},
                                                   {'typ': 'Public'}],
                                 'vlan': None}],
         'pods': [{'XRT_PodIPRangeSize': 10,
                    'clusters': [{'XRT_Hosts': 1,
                                   'XRT_KVMHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'CloudManaged',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://10.0.0.3',
                                              'username': 'root'}],
                                   'hypervisor': 'KVM',
                                   'primaryStorages': [{'name': 'XenRT-Zone-0-Pod-0-Cluster-0-Primary-Store-0',
                                                        'url': 'nfs://nfsserver/path'}]}],
                    'guestIpRanges': [{'endip': '10.1.0.20',
                                       'gateway': '10.3.1.2',
                                       'netmask': '255.255.255.0',
                                       'startip': '10.1.0.1'}],
                    'endip': '10.1.0.10',
                    'gateway': '10.3.1.2',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.255.0',
                    'startip': '10.1.0.1'}],
         'secondaryStorages': [{'provider': 'NFS',
                                'url': 'nfs://nfsserver/path'}]}]} 


