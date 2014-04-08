from mock import patch, Mock, MagicMock
from testing import XenRTUnitTestCase
import xenrt
from testcases.xenserver.tc.multipath import DellPowerVaultIscsiMultipath

class TestDellPowerVaultIscsiMultipath(XenRTUnitTestCase):
	
	@patch("xenrt.resources.LocalDirectoryResourceImplementer")
	@patch("xenrt.TEC")
	@patch("xenrt.GEC")
	def setUp(self,gec,tec,res):
		self.test = DellPowerVaultIscsiMultipath()
		self.test.host = Mock()

	def test_multipathInfo(self):
		"""Given multipath -ll command output , when passed to multipathinfo , then output is as expected (primary and secondary groups)"""
		data_input_expected =[("123456abc dm-1\n policy status=enabled\n| |- d sda c failed a b \n| `- d sdb c failed a b\n policy status=enabled\n| |- d sdc c failed a b \n| `- d sdd c failed a b\n",{'status':'enabled',0:['sda','failed'],1:['sdb','failed']},{'status':'enabled',0:['sdc','failed'],1:['sdd','failed']}),
				      ("",{},{})]

		self.run_for_many(data_input_expected, self.__test_multipathInfo)

    	def __test_multipathInfo(self,data_input_expected):
		"""
		Get the multipath -ll output in form of primary and secondary groups
        	primary = {'status':['active'/'enable'], 0:['sda', 'active'/'failed'], 1:['sdb', 'active'/'failed']}
        	secondary = {'status':['active'/'enable'], 0:['sdc', 'active'/'failed'], 1:['sdd', 'active'/'failed']}
		"""
		inputs, pri_expected, sec_expected = data_input_expected
		self.test.host.execdom0 = Mock(return_value = inputs)
		pri_actual , sec_actual = self.test.multipathInfo()
		self.assertEqual(pri_expected , pri_actual)
		self.assertEqual(sec_expected , sec_actual)

	def test_multipathGroupStatus(self):
		"""Given raw Group data , when passed to multipathGroupstatus , then output is formatted to point status of primary and secondary group"""
		group_data = [("status=active",{'status':'active',0:[]}),
		              ("status=enabled",{'status':'enabled',0:[]})]
		self.run_for_many(group_data, self.__test_multipathGroupStatus)

    	def __test_multipathGroupStatus(self,group_data):
		inputs , group_expected = group_data
        	group_actual = self.test._multipathGroupStatus(inputs, {},0)
        	self.assertEqual(group_expected, group_actual)
	
	def test_multipathPathsStatus(self):
		"""Given raw Multipath Paths data , when passed to multipathPathsStatus, then output parsed to primary and secondary paths """
		paths_data = [("| |- d sda c failed a b \n",(1, {0: ['sda', 'failed']},{}))]
		self.run_for_many(paths_data, self.__test_multipathPathsStatus)

	def __test_multipathPathsStatus(self,paths_data):
		inputs, paths_expected = paths_data
		paths_actual = self.test._multipathPathsStatus(0,{},{},inputs)
		self.assertEqual(paths_expected,paths_actual)
	
	def test_multipathInfoFlow(self):
		"""Given multipath -ll output , when passed to multipathinfo , then flow of test happens correctly with functions called and flags set"""
		inputs = "123456abc dm-1\n policy status=enabled\n| |- d sda c failed a b \n"
		self.test.host.execdom0 = Mock(return_value = inputs)
		self.test._multipathPathsStatus = Mock(return_value=(1, {0: ['sda', 'failed']}, {}))
        	self.test._multipathGroupStatus = Mock(return_value={'status': 'active', 0: []})
		pri_actual , sec_actual = self.test.multipathInfo()
		self.assertEqual(1,self.test._multipathGroupStatus.call_count)
		self.assertEqual(1,self.test._multipathPathsStatus.call_count)
