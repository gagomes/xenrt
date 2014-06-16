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
                    "CLOUDINPUTDIR": "http://repo/location",
                    "ROOT_PASSWORD": "xenroot",
                    }

    def addTC(self, cls):
        self.tcs.append((cls.IN, cls.OUT, cls.EXTRAVARS))

    def test_marvin_config_generator(self):
        self.tcs = []
        self.addTC(TC1)
        self.addTC(TC2)
        self.run_for_many(self.tcs, self.__test_marvin_config_generator)

    @patch("xenrt.ExternalNFSShare")
    @patch("xenrt.command")
    @patch("xenrt.TempDirectory")
    @patch("xenrt.StaticIP4Addr.getIPRange")
    @patch("xenrt.PrivateVLAN.getVLANRange")
    @patch("xenrt.GEC")
    @patch("xenrt.TEC")
    def __test_marvin_config_generator(self, data, tec, gec, pvlan, ip, td, cmd, nfs):
        ip.side_effect = self.__getIPRange
        pvlan.side_effect = self.__getVLANRange
        self.dummytec = DummyTEC(self)
        dummyNfs = Mock()
        dummyNfs.getMount.return_value = "server:/path"
        nfs.return_value = dummyNfs
        tec.return_value = self.dummytec
        gec.return_value = self.dummytec
        (indata, outdata, extravars) = data
        self.extravars = extravars
        unit = xenrt.lib.cloud.marvindeploy.MarvinDeployer("1.1.1.1", Mock(), "root", "xenroot", None)
        cfg = copy.deepcopy(indata)

        marvin = Mock()

        marvin.createSecondaryStorage.side_effect = self.__createSecStorage

        deployer = xenrt.lib.cloud.deploy.DeployerPlugin(marvin)
        unit._processConfigElement(cfg, 'config', deployer)
        print "Input Data"
        pprint.pprint(indata)
        print "Expected"
        pprint.pprint(outdata)
        print "Actual"
        pprint.pprint(cfg)
        self.assertEqual(outdata, cfg)

    def _lookup(self, var, default="BADVALUE"):
        values = {}

        if isinstance(var, list):
            var = "/".join(var)

        values.update(self.DEFAULT_VARS)
        values.update(self.extravars)
        if not values.has_key(var):
            if default == "BADVALUE":
                raise Exception("No default value specified for test")
            return default
        else:
            return values[var]

    def __createSecStorage(self, secStorageType):
        if secStorageType == "SMB":
            return "cifs://10.0.0.3/storage/secondary"
        else:
            return "nfs://secsever/secpath"

    @classmethod
    def __getVLANRange(cls, size):
        vlans = []
        for i in range(size):
            m = Mock()
            m.getID.return_value = 3000+i
            vlans.append(m)
        return vlans

    @classmethod
    def __getIPRange(cls, size):
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
        print msg

    def lookup(self, var, default="BADVALUE"):
        return self.parent._lookup(var, default)

    def getFile(self, *files):
        return "/path/to/file"

    @property
    def config(self):
        return self

class DummyRegistry(object):
    def hostGet(self, h):
        index = int(re.match("RESOURCE_HOST_(\d+)", h).group(1))
        m = Mock()
        m.getIP.return_value = str(IPy.IP(IPy.IP("10.0.0.3").int() + index))
        return m

class BaseTC(object):
    EXTRAVARS = {}

class TC1(BaseTC):
    """Test that Hyper-V zones use SMB storage"""

    EXTRAVARS={"CIFS_HOST_INDEX": "0"}

    IN = {u'zones': [{u'guestcidraddress': u'192.168.200.0/24',
             u'ipranges': [{u'XRT_GuestIPRangeSize': 10}],
             u'networktype': u'Advanced',
             u'physical_networks': [{u'XRT_VLANRangeSize': 10,
                                     u'isolationmethods': [u'VLAN'],
                                     u'name': u'AdvPhyNetwork',
                                     u'providers': [{u'broadcastdomainrange': u'ZONE',
                                                     u'name': u'VirtualRouter'},
                                                    {u'broadcastdomainrange': u'ZONE',
                                                     u'name': u'VpcVirtualRouter'},
                                                    {u'broadcastdomainrange': u'ZONE',
                                                     u'name': u'InternalLbVm'}],
                                     u'traffictypes': [{u'typ': u'Guest'},
                                                       {u'typ': u'Management'},
                                                       {u'typ': u'Public'}]}],
             u'pods': [{u'XRT_PodIPRangeSize': 10,
                        u'clusters': [{u'XRT_Hosts': 1,
                                       'XRT_HyperVHostIds': '0',
                                       u'hypervisor': u'hyperv'}]}]}]}

    OUT = {u'zones': [{'dns1': '10.0.0.2',
         u'guestcidraddress': u'192.168.200.0/24',
         'internaldns1': '10.0.0.2',
         u'ipranges': [{u'XRT_GuestIPRangeSize': 10,
                        'endip': '10.1.0.10',
                        'gateway': '10.0.0.1',
                        'netmask': '255.255.255.0',
                        'startip': '10.1.0.1'}],
         'name': 'XenRT-Zone-0',
         u'networktype': u'Advanced',
         u'physical_networks': [{u'XRT_VLANRangeSize': 10,
                                 'broadcastdomainrange': 'Zone',
                                 u'isolationmethods': [u'VLAN'],
                                 u'name': u'AdvPhyNetwork',
                                 u'providers': [{u'broadcastdomainrange': u'ZONE',
                                                 u'name': u'VirtualRouter'},
                                                {u'broadcastdomainrange': u'ZONE',
                                                 u'name': u'VpcVirtualRouter'},
                                                {u'broadcastdomainrange': u'ZONE',
                                                 u'name': u'InternalLbVm'}],
                                 u'traffictypes': [{u'typ': u'Guest'},
                                                   {u'typ': u'Management'},
                                                   {u'typ': u'Public'}],
                                 'vlan': '3000-3009'}],
         u'pods': [{u'XRT_PodIPRangeSize': 10,
                    u'clusters': [{u'XRT_Hosts': 1,
                                   'XRT_HyperVHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'CloudManaged',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://10.0.0.3',
                                              'username': 'root'}],
                                   u'hypervisor': u'hyperv',
                                   'primaryStorages': [{'details': [{'user': 'Administrator'},
                                                                    {'password': 'xenroot01T'},
                                                                    {'domain': 'XSQA'}],
                                                        'name': 'XenRT-Zone-0-Pod-0-Primary-Store',
                                                        'url': 'cifs://10.0.0.3/storage/primary'}]}],
                    'endip': '10.1.0.10',
                    'gateway': '10.0.0.1',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.255.0',
                    'startip': '10.1.0.1'}],
         'secondaryStorages': [{'details': {'domain': 'XSQA',
                                            'password': 'xenroot01T',
                                            'user': 'Administrator'},
                                'provider': 'SMB',
                                'url': 'cifs://10.0.0.3/storage/secondary'}]}]} 

class TC2(BaseTC):
    """Test that KVM zones use NFS storage"""

    IN = {u'zones': [{u'guestcidraddress': u'192.168.200.0/24',
             u'ipranges': [{u'XRT_GuestIPRangeSize': 10}],
             u'networktype': u'Advanced',
             u'physical_networks': [{u'XRT_VLANRangeSize': 10,
                                     u'isolationmethods': [u'VLAN'],
                                     u'name': u'AdvPhyNetwork',
                                     u'providers': [{u'broadcastdomainrange': u'ZONE',
                                                     u'name': u'VirtualRouter'},
                                                    {u'broadcastdomainrange': u'ZONE',
                                                     u'name': u'VpcVirtualRouter'},
                                                    {u'broadcastdomainrange': u'ZONE',
                                                     u'name': u'InternalLbVm'}],
                                     u'traffictypes': [{u'typ': u'Guest'},
                                                       {u'typ': u'Management'},
                                                       {u'typ': u'Public'}]}],
             u'pods': [{u'XRT_PodIPRangeSize': 10,
                        u'clusters': [{u'XRT_Hosts': 1,
                                       'XRT_KVMHostIds': '0',
                                       u'hypervisor': u'kvm'}]}]}]}

    OUT = {u'zones': [{'dns1': '10.0.0.2',
         u'guestcidraddress': u'192.168.200.0/24',
         'internaldns1': '10.0.0.2',
         u'ipranges': [{u'XRT_GuestIPRangeSize': 10,
                        'endip': '10.1.0.10',
                        'gateway': '10.0.0.1',
                        'netmask': '255.255.255.0',
                        'startip': '10.1.0.1'}],
         'name': 'XenRT-Zone-0',
         u'networktype': u'Advanced',
         u'physical_networks': [{u'XRT_VLANRangeSize': 10,
                                 'broadcastdomainrange': 'Zone',
                                 u'isolationmethods': [u'VLAN'],
                                 u'name': u'AdvPhyNetwork',
                                 u'providers': [{u'broadcastdomainrange': u'ZONE',
                                                 u'name': u'VirtualRouter'},
                                                {u'broadcastdomainrange': u'ZONE',
                                                 u'name': u'VpcVirtualRouter'},
                                                {u'broadcastdomainrange': u'ZONE',
                                                 u'name': u'InternalLbVm'}],
                                 u'traffictypes': [{u'typ': u'Guest'},
                                                   {u'typ': u'Management'},
                                                   {u'typ': u'Public'}],
                                 'vlan': '3000-3009'}],
         u'pods': [{u'XRT_PodIPRangeSize': 10,
                    u'clusters': [{u'XRT_Hosts': 1,
                                   'XRT_KVMHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'CloudManaged',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://10.0.0.3',
                                              'username': 'root'}],
                                   u'hypervisor': u'kvm',
                                   'primaryStorages': [{'name': 'XenRT-Zone-0-Pod-0-Primary-Store',
                                                        'url': 'nfs://server/path'}]}],
                    'endip': '10.1.0.10',
                    'gateway': '10.0.0.1',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.255.0',
                    'startip': '10.1.0.1'}],
         'secondaryStorages': [{'provider': 'NFS',
                                'url': 'nfs://server/path'}]}]} 

