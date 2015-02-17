from xenrt.lib.xenserver.readcaching import ReadCachingController
from testing import XenRTUnitTestCase
from mock import Mock


class TestReadCachingLowLevelController(XenRTUnitTestCase):

    __TAP_CTRL_LIST = """pid=%s minor=%s state=0 args=vhd:/dev/VG_XenStorage-%s"""
    __STAT_CMD = "tap-ctl stats -p %s -m %s"

    def __createMockHost(self, dataList):

        tapList = []
        calls = {}
        for pid, minor, uuid, statOutput in dataList:
            tapList.append(self.__TAP_CTRL_LIST % (pid, minor, uuid))
            calls[self.__STAT_CMD % (pid, minor)] = statOutput

        calls["tap-ctl list | cat"] = '\n'.join(tapList)
        host = Mock()
        host.execdom0 = Mock()
        host.execdom0.side_effect = lambda x: calls[x]
        return host

    def testTapCtlWithExpectedOutputReadCacheEnabled(self):
        data = [("1", "2", "1-2", """{"reqs_oustanding": 0, "read_caching": "false" }"""),
                ("2", "3", "2-3", """{"reqs_oustanding": 0, "read_caching": "true" }""")]
        host = self.__createMockHost(data)
        rc = ReadCachingController(host, "2-3")
        self.assertTrue(rc.isEnabled(lowLevel=True))

    def testTapCtlWithExpectedOutputReadCacheDisabled(self):
        data = [("1", "2", "1-2", """{"reqs_oustanding": 0, "read_caching": "false" }"""),
                ("2", "3", "2-3", """{"reqs_oustanding": 0, "read_caching": "true" }""")]
        host = self.__createMockHost(data)
        rc = ReadCachingController(host, "1-2")
        self.assertFalse(rc.isEnabled(lowLevel=True))
