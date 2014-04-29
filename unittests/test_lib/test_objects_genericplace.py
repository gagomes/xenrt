import xenrt
from mock import Mock, patch,PropertyMock
from testing import XenRTUnitTestCase
from xenrt.objects import GenericPlace

class GenericPlaceDouble(GenericPlace):
	def __init__(self): pass

class TestGenericPlace(XenRTUnitTestCase):
	
	def setUp(self):
		self.genericobject = GenericPlaceDouble()
	
	@patch("xenrt.util.parseSectionedConfig")			
	def test_getwindowsnetshconfig_validcmd_returnexpected(self,parse):
		"""
		Given a clean windows environment , when netsh configuration information is provided with xmlrpc support, then it returns as expected
		"""
		self.genericobject.xmlrpcExec = Mock(return_value="connection established")
		parse = Mock(return_value="blah")
		self.genericobject.getWindowsNetshConfig("netsh mock interface")
		self.assertTrue(self.genericobject.xmlrpcExec.called)
		self.assertTrue(xenrt.util.parseSectionedConfig.called)
	
	def test_getlinuxifconfigdata_validinput_returnexpected(self):
		"""
		Given clean linux environment , when ipconfig data is provided , then output will be in  expected format
		"""
		data = [("eth0  Link encap:Ethernet  HWaddr 52:f2:da:cc:72:fa  \n  inet addr:10.220.169.47  Bcast:10.220.175.255  Mask:255.255.240.0",
			{'eth0': {'IP': '10.220.169.47', 'MAC': '52:f2:da:cc:72:fa', 'netmask': '255.255.240.0'}}),
			("lo  Link encap:Local Loopback  \n  inet addr:127.0.0.1  Mask:255.0.0.0",
			{'lo': {'IP': '127.0.0.1', 'MAC': None, 'netmask': '255.0.0.0'}})]
		self.run_for_many(data,self.__test_getlinuxifconfigdata_validinput_returnexpected)

	def __test_getlinuxifconfigdata_validinput_returnexpected(self,data):
		"""
		Given clean linux environment, when execcmd support is provided , then parsed ifconfig is returned
		"""
		ifconfigoutput, expected = data
		self.genericobject.execcmd = Mock(return_value=ifconfigoutput)
		output = self.genericobject.getLinuxIFConfigData()	
		self.assertTrue(self.genericobject.execcmd.called)
		self.assertEqual(expected,output)
 
	def test_getwindowsipconfigdata_validinput_returnexpected(self):
		"""
		Given clean windows environment , when ipconfig data is provided with xmlrpcexec supported , then output is as expected 
		"""
		data = [("Enet 1:\n\n   PhyAdd. : AE\n   Ipv4. : 142\n   SMask . : 255\n   DGate . : 127.1\n   DServer . : 11\n",
			{'Enet 1': {'DServer': '11', 'DGate': '127.1', 'SMask': '255', 'PhyAdd': 'AE', 'Ipv4': '142'}}),
			("",{})
			]	
		self.run_for_many(data,self.__test_getwindowsipconfigdata_validinput_returnexpected)

	def __test_getwindowsipconfigdata_validinput_returnexpected(self,data):
		"""
		Given clean windows environment , when xmlrpcexec support is provided, then parsed ipconfig data is returned	
		"""
		ipconfigoutput, expected = data
		self.genericobject.xmlrpcExec = Mock(return_value = ipconfigoutput)
		output = self.genericobject.getWindowsIPConfigData()
		self.assertTrue(self.genericobject.xmlrpcExec.called)
		self.assertEqual(expected,output)
	
	def __initializegetwindowsinterface(self,data):
		ipconfigdata,vifs,vifstem,device_input = data
		self.genericobject.getWindowsIPConfigData = Mock(return_value =ipconfigdata )
                self.genericobject.getVIFs = Mock(return_value =vifs )
                self.genericobject.vifstem = vifstem
                self.device = device_input

	def test_getwindowsinterface_validinput_returninterface(self):
		"""
		Given a clean windows environment ,when ip configuration data is provided, then interface is returned	
		"""	
		data = ({'Ethernet2': {'IPv4 Address': '10.102.127.142', 'Physical Address': 'AE-D9-CF-D4-94-71'}},
			{'Ethernet2': ('ae:d9:cf:d4:94:71','10.102.127.142', '12345678')},"Ethernet","Ethernet2")
		expected_key = "Ethernet2"
		self.__initializegetwindowsinterface(data)
		key = self.genericobject.getWindowsInterface(self.device)
		self.assertTrue(self.genericobject.getWindowsIPConfigData.called)
		self.assertEqual(expected_key , key)

	def test_getwindowsinterface_invalidinputMACnotmatching_raiseexception(self):
		"""
		Given clean windows environment, when invalid ip(MAC not matching) configuration data is provided , then it raises exception
		"""
		data = ({'Ethernet1': {'IPv4 Address': '10.102.127.142', 'Physical Address': 'AE-D9-CF-D4-94-72'}},
			{'Ethernet2': ('ae:d9:cf:d4:94:71','10.102.127.142', '12345678')},"Ethernet","Ethernet2")
		self.__initializegetwindowsinterface(data)
		self.assertRaises(xenrt.XRTError,self.genericobject.getWindowsInterface,"Ethernet2")
	
	def test_getwindowsinterface_invalidinputnophysicaladdress_raiseexception(self):
                """
                Given clean windows environment, when invalid ip(Physical address missing) configuration data is provided , then it raises exception
                """
                data = ({'Ethernet1': {'IPv4 Address': '10.102.127.142'}},
                        {'Ethernet2': ('ae:d9:cf:d4:94:71','10.102.127.142', '12345678')},"Ethernet","Ethernet2")
                self.__initializegetwindowsinterface(data)
                self.assertRaises(xenrt.XRTError,self.genericobject.getWindowsInterface,"Ethernet2")
