from mock import patch, Mock, PropertyMock
import xenrt
from testing import XenRTUnitTestCase

import copy

import pprint

class TestMarvinConfig(XenRTUnitTestCase):

    DEFAULT_VARS = {}

    def addTC(self, cls):
        self.tcs.append((cls.IN, cls.OUT, cls.EXTRAVARS))

    def test_marvin_config_generator(self):
        self.tcs = []
        self.addTC(TC1)
        self.run_for_many(self.tcs, self.__test_marvin_config_generator)

    @patch("xenrt.TEC")
    def __test_marvin_config_generator(self, data, tec):
        # Replace lookup with a custom function
        tec.return_value.lookup=self.__mylookup
        (indata, outdata, extravars) = data
        self.extravars = extravars

        unit = xenrt.lib.cloud.marvindeploy.MarvinDeployer("1.1.1.1", Mock(), "root", "xenroot", None)
        cfg = copy.deepcopy(indata)

        marvin = Mock()

        deployer = xenrt.lib.cloud.deploy.DeployerPlugin(marvin)
        unit._processConfigElement(cfg, 'config', deployer)
        pprint.pprint(cfg)

    def __mylookup(self, var, default="BADVALUE"):
        values = {}

        if isinstance(var, list):
            var = "/".join(var)

        values.update(self.DEFAULT_VARS)
        values.update(self.extravars)
        if not values.has_key(var):
            if default == "BADVALUE":
                raise Exception("No default value specified")
            return default
        else:
            return values[var]

class TC1:

    EXTRAVARS = {}

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

    OUT = {u'zones': [{'dns1': '10.220.160.11',
         u'guestcidraddress': u'192.168.200.0/24',
         'internaldns1': '10.220.160.11',
         u'ipranges': [{u'XRT_GuestIPRangeSize': 10,
                        'endip': '10.220.164.49',
                        'gateway': '10.220.160.1',
                        'netmask': '255.255.240.0',
                        'startip': '10.220.164.40'}],
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
                                 'vlan': '3010-3019'}],
         u'pods': [{u'XRT_PodIPRangeSize': 10,
                    u'clusters': [{u'XRT_Hosts': 1,
                                   'XRT_HyperVHostIds': '0',
                                   'clustername': 'XenRT-Zone-0-Pod-0-Cluster-0',
                                   'clustertype': 'CloudManaged',
                                   'hosts': [{'password': 'xenroot',
                                              'url': 'http://10.220.163.51',
                                              'username': 'root'}],
                                   u'hypervisor': u'hyperv',
                                   'primaryStorages': [{'details': [{'user': 'Administrator'},
                                                                    {'password': 'xenroot01T'},
                                                                    {'domain': 'XSQA'}],
                                                        'name': 'XenRT-Zone-0-Pod-0-Primary-Store',
                                                        'url': 'cifs://10.220.163.51/storage/primary'}]}],
                    'endip': '10.220.164.59',
                    'gateway': '10.220.160.1',
                    'name': 'XenRT-Zone-0-Pod-0',
                    'netmask': '255.255.240.0',
                    'startip': '10.220.164.50'}],
         'secondaryStorages': [{'details': {'domain': 'XSQA',
                                            'password': 'xenroot01T',
                                            'user': 'Administrator'},
                                'provider': 'SMB',
                                'url': 'cifs://10.220.163.51/storage/secondary'}]}]} 
