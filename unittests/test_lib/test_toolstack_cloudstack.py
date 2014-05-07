from testing import XenRTUnitTestCase
from mock import patch, Mock
import xenrt


class VMListDataDouble(object):
        def __init__(self, name):
            self.hostname = name


class testCloudStackResidentOn(XenRTUnitTestCase):

    def setUp(self):
        # Setup class-scoped mocks to replace the call to instance.toolstack
        self.__id = Mock(return_value=1)
        self.__instance = Mock()
        self.__instance.toolstackId = self.__id

        # Self class under test
        self.__cut = xenrt.lib.cloud.toolstack.CloudStack(place="MyPlace")

    @patch("marvin.integration.lib.base.VirtualMachine.list")
    def testResidentOnGivesTheZerothHostNameWithListOfData(self, vm):
        """Given CloudStack returns a selection of VMs in a list
        when the residency is requested then expect the zeroth host name to
        be returned """

        desiredHostName = "FatherJack"
        vm.return_value = [VMListDataDouble(desiredHostName),
                           VMListDataDouble("FatherTed")]

        result = self.__cut.instanceResidentOn(self.__instance)
        self.assertEqual(desiredHostName, result)

    @patch("marvin.integration.lib.base.VirtualMachine.list")
    def testEmptyListOfCloudStackDataRaises(self, vm):
        """Given CloudStack returns an emptyVM list
        when the residency is requested then expect an exception
        """

        vm.return_value = []
        with self.assertRaises(IndexError):
            self.__cut.instanceResidentOn(self.__instance)
