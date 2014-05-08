from testing import XenRTUnitTestCase
from mock import Mock
import xenrt


class VMListDataDouble(object):
        def __init__(self, name):
            self.hostname = name


class CloudStackDouble(xenrt.lib.cloud.toolstack.CloudStack):
    """
    Double of the class under test
    Fake out the call to get a list of VMs from the cloud
    """
    def __init__(self, listResult):
        super(CloudStackDouble, self).__init__(place="MyPlace")
        self.__results = listResult

    def _vmListProvider(self, toolstackid):
        return self.__results


class testCloudStackResidentOn(XenRTUnitTestCase):

    def setUp(self):
        # Setup class-scoped mocks to replace the call to instance.toolstack
        self.__id = Mock(return_value=1)
        self.__instance = Mock()
        self.__instance.toolstackId = self.__id

    def testResidentOnGivesTheZerothHostNameWithListOfData(self):
        """Given CloudStack returns a selection of VMs in a list
        when the residency is requested then expect the zeroth host name to
        be returned """

        desiredHostName = "FatherJack"
        data = [VMListDataDouble(desiredHostName),
                VMListDataDouble("FatherTed")]

        cut = CloudStackDouble(data)
        result = cut.instanceResidentOn(self.__instance)
        self.assertEqual(desiredHostName, result)

    def testEmptyListOfCloudStackDataRaises(self):
        """Given CloudStack returns an emptyVM list
        when the residency is requested then expect an exception
        """

        cut = CloudStackDouble([])
        with self.assertRaises(IndexError):
            cut.instanceResidentOn(self.__instance)
