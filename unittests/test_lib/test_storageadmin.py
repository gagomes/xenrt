from mock import patch, Mock
from testing import XenRTUnitTestCase
import xenrt

"""Mockable doubles"""
class ServerDouble(object):
    def invoke(self, *args): pass 

class DataDouble(object):
    def children_get(self): pass
    def child_get(self, key): pass
    def child_get_string(self, key): pass

"""Tests"""
class TestNetAppFCInitiatorGroup(XenRTUnitTestCase):
    
    def setUp(self):
        self.sd = ServerDouble()
        self.ig = xenrt.storageadmin.NetAppFCInitiatorGroup(self.sd)
        self.name = "randomname"
        self.ig._generateRandomName = Mock(return_value=self.name)

    @patch("xenrt.storageadmin.NetAppStatus")
    def test_create(self, nas):
        self.sd.invoke = Mock(return_value="mockresult")
        self.ig._raiseApiFailure = Mock()
        self.ig.create()
        args = ['igroup-create', 'initiator-group-name', 
                self.name, 'initiator-group-type', 'fcp', 'os-type', 'linux']
        self.sd.invoke.assert_called_with(*args)

    @patch("xenrt.storageadmin.NetAppStatus")
    @patch("xenrt.storageadmin.NetAppInitiatorGroupCommunicator")
    def test_list(self, comm, nas):
        parsedMsg = "Parsed Message"
        results = "Mock results"
        self.sd.invoke = Mock(return_value=results)
        self.ig._raiseApiFailure = Mock()
        comm.return_value.parseListMessage.return_value=parsedMsg

        parsedResults = self.ig.list()
       
        comm.return_value.parseListMessage.assert_called_with(results)
        self.assertEqual(parsedMsg, parsedResults) 
    

class TestNetAppInitiatorGroupCommunicator(XenRTUnitTestCase):
    
    def setUp(self):
        self.sd = ServerDouble()
        self.ig = xenrt.storageadmin.NetAppInitiatorGroupCommunicator()

    def __create_initiator_list(self, numberRequired, seedName):
        outputList = [] 
        for x in range(numberRequired):
            initiator = DataDouble()
            initiator.child_get_string = Mock(return_value = seedName + str(x))
            outputList.append(initiator)
        
        iList = DataDouble()
        iList.children_get = Mock(return_value = outputList)
        return iList
        
    def __create_mock_igroup(self, iname, igname, itype, iNum):
        iGroupData = lambda x: {"initiator-group-type" : itype,
                                "initiator-group-name": igname}[x]
        iGroup = DataDouble()
        iGroup.child_get_string = Mock(side_effect = iGroupData)
        iGroup.child_get = Mock(return_value = self.__create_initiator_list(iNum,iname))
        return iGroup

    @patch("xenrt.storageadmin.NetAppStatus")
    def __list_parsing_with_duplicate_igroup_names(self, iname, igname, itype, expected, nas):
        
        iGroup = self.__create_mock_igroup(iname, igname, itype, 2)
        igi = DataDouble()
        igi.children_get = Mock(return_value=[iGroup, iGroup])
        
        results = DataDouble()
        results.child_get = Mock(return_value = igi)

        self.sd.invoke = Mock(return_value = results)
        self.ig._raiseApiFailure = Mock()
        self.assertEqual(expected, self.ig.parseListMessage(results))

    """
    Test methods
    """
    def test_list_parsing_with_duplicate_igroup_names(self):
        iname = "mockinitiatorname"
        igname = "mockigroupname"
        itype = "fcp"
        expected = {igname: [iname+"0", iname+"1"]}
        self.__list_parsing_with_duplicate_igroup_names(iname, igname, itype, expected)
    
    def test_list_parsing_with_non_fcp(self):
        iname = "mockinitiatorname"
        igname = "mockigroupname"
        itype = "blahblah"
        expected = {}
        self.__list_parsing_with_duplicate_igroup_names(iname, igname, itype, expected)

    def test_failure_with_non_string_args(self):
        for x in ["bad stuff", 2, ["hi", "bye"], {"name" : "bob"}, None, ""]:
            self.assertRaises(AttributeError, self.ig.parseListMessage, x)
    
    @patch("xenrt.storageadmin.NetAppStatus")
    def test_mutiple_igroup_names_and_types(self, nas):
        iname = "mockinitiatorname"
        igname = "mockigroupname"
        ignameSecond = "mockigroupname2"
        itype = "fcp"
        iGroupA = self.__create_mock_igroup(iname, igname, itype, 2)
        iGroupB = self.__create_mock_igroup(iname, ignameSecond, itype, 3)
        iGroupC = self.__create_mock_igroup(iname, "IShouldNotAppear", "RandomNonesense", 2)
        igi = DataDouble()
        igi.children_get = Mock(return_value=[iGroupA, iGroupB, iGroupC])
        
        results = DataDouble()
        results.child_get = Mock(return_value = igi)

        self.sd.invoke = Mock(return_value = results)
        self.ig._raiseApiFailure = Mock()
        expected = {ignameSecond: [ iname + '0', iname+ '1', iname + '2'], 
                    igname: [iname +'0', iname + '1']}
        self.assertEqual(expected, self.ig.parseListMessage(results))
        
