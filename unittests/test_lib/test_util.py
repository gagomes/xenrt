import xenrt
from testing import XenRTUnitTestCase
from mock import Mock, PropertyMock

"""Tests"""
class TestParseSectionedConfig(XenRTUnitTestCase):
	
	def side_effect(self,arg):
		values =   {"ipconfig":["(?m)^(\S[^:]*):?\n\n((?:^[\ \t]+\S.*\n)+)",
					"\s+([^\.:]+)(?:\.\ )+:(.*\n(?:(?:[^:]+\n)*))",
					"Windows IP\n\n   Host. : ddc\n\nEthernet 2:\n\n   Physical. : AE-D9-CF-D4-94-71\n   IPv4. : 10.102.127.142\n",
					"{'Windows IP': {'Host': 'ddc'}, 'Ethernet 2': {'IPv4': '10.102.127.142', 'Physical': 'AE-D9-CF-D4-94-71'}}"],
			    "netsh":["^Configuration for interface \"(?m)([^\"]+)\"\n((?:^[\ \t]+\S.*\n)+)",
					"\s*([^:\n]+)(?:\n|:\s*(.*\n?(?:\s*\d[^:]+\n)*)?)",
					"Configuration for interface \"Eth2\"\n    IP:10.102.127.142\n    Subnet:10.102.127.0\n    Gateway:10.102.127.1\n",
					"{'Eth2': {'IP': '10.102.127.142', 'Gateway': '10.102.127.1', 'Subnet': '10.102.127.0'}}"]}
		return values[arg]

	def __intializeparsesectionedconfig(self,inputs):
		mock = Mock()
		mock.side_effect = self.side_effect
		self.secpatt,self.fieldpatt,self.data,self.expected =  mock(inputs)

	def test_parsesectionedconfig_validipconfigdata_returnexpected(self):
		"""
		Given clean windows environment,when ipconfig command output is provided ,then it returns sectioned configuration as two-layer's dictionary
		"""
		self.__intializeparsesectionedconfig("ipconfig")
		parsedoutput = xenrt.util.parseSectionedConfig(self.data,self.secpatt,self.fieldpatt)
		self.assertEqual(self.expected ,str(parsedoutput))
	
	def test_parsesectionedconfig_validnetshconfigdata_returnexpected(self):
		"""
		Given clean windows environment , when netsh command output is provided ,then it returns sectioned configuration as two-layer's dictionar
		"""
		self.__intializeparsesectionedconfig("netsh")
                parsedoutput = xenrt.util.parseSectionedConfig(self.data,self.secpatt,self.fieldpatt)
                self.assertEqual(self.expected ,str(parsedoutput)) 

class TestDistroParsing(XenRTUnitTestCase):
    def test_distroparsing(self):
        """
        Test that we get the correct distro/arch for distro text
        """
        tests = {"rhel64-x64": ("rhel64", "x86-64"),
                 "rhel64-x86": ("rhel64", "x86-32"),
                 "rhel64-x32": ("rhel64", "x86-32"),
                 "rhel64_x86-32": ("rhel64", "x86-32"),
                 "rhel64_x86-64": ("rhel64", "x86-64"),
                 "rhel64": ("rhel64", "x86-32")}

        for t in tests.keys():
            self.assertEqual(tests[t], xenrt.getDistroAndArch(t))
                 
