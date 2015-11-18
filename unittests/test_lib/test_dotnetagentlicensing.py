
import testing
import xenrt.lib.xenserver.dotnetagentlicensing as dnl
import mock


class TestVMUserActorCheckKeyPresent(testing.XenRTUnitTestCase):

    def __createMockOS(self, regKeyExists, regLookupReturnValue):
        mockOS = mock.Mock()
        mockOS.winRegExists = mock.Mock(return_value=regKeyExists)
        mockOS.winRegLookup = mock.Mock(return_value=regLookupReturnValue)
        return mockOS

    @mock.patch("xenrt.TEC")
    def test_checkKeyPresentFound(self, tec):
        cut = dnl.VMUser(None, self.__createMockOS(True, "Fish fingers are the best"))
        self.assertTrue(cut.checkKeyPresent(), "key is present")

    @mock.patch("xenrt.TEC")
    def test_checkKeyPresentNotFound(self, tec):
        cut = dnl.VMUser(None, self.__createMockOS(False, "Hammer Time"))
        self.assertFalse(cut.checkKeyPresent(), "key is present")

    @mock.patch("xenrt.TEC")
    def test_checkKeyPresentButNoValueSet(self, tec):
        cut = dnl.VMUser(None, self.__createMockOS(True, None))
        self.assertFalse(cut.checkKeyPresent(), "key is present")


class ActorDouble(dnl.ActorAbstract):
    def isLicensed(self):
        return True


class TestActorAbstract(testing.XenRTUnitTestCase):

    @mock.patch("xenrt.TEC")
    def testActorPassesThroughCheckKeyPresent(self, tec):
        mockActor = mock.Mock()
        mockActor.checkKeyPresent = mock.Mock(return_value=True)

        cut = ActorDouble()
        cut.setActor(mockActor)
        self.assertTrue(cut.checkKeyPresent())
