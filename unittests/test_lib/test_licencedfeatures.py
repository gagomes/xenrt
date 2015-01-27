from xenrt.lib.xenserver.licensedfeatures import WorkloadBalancing, ReadCaching, VirtualGPU, Hotfixing, ExportPoolResourceList, GPUPassthrough, LicensedFeatureFactory
from testing import XenRTUnitTestCase
from mock import Mock


class TestLicencedFeatures(XenRTUnitTestCase):

    __UI_FEATURES = [Hotfixing(), ExportPoolResourceList(), WorkloadBalancing()]
    __SERVER_SIDE_FEATURES = [ReadCaching(), VirtualGPU(), GPUPassthrough()]

    def testUIFlaggableStatesIndicateEnableCannotBeChecked(self):
        for feature in self.__UI_FEATURES:
            self.assertFalse(feature.stateCanBeChecked)

    def testServerSideFlaggableStatesIndicateEnableCanBeChecked(self):
        for feature in self.__SERVER_SIDE_FEATURES:
            self.assertTrue(feature.stateCanBeChecked)

    def testUIFeaturesIsEnabledThrows(self):
        for feature in self.__UI_FEATURES:
            self.assertRaises(NotImplementedError, feature.isEnabled, None)


class TestLicencedHostFeatureFlags(XenRTUnitTestCase):

    def __createMockHost(self, fakeOutput):
        host = Mock()
        cli = Mock()
        host.getCLIInstance = Mock(return_value=cli)
        cli.execute = Mock(return_value=fakeOutput)
        return host

    def testHostFeatureFlagFoundAndTrue(self):
        fakeOutput = """
               restrict_email_alerting: false
       restrict_historical_performance: false
                          restrict_wlb: true
                         restrict_rbac: false
                          restrict_dmc: false"""
        host = self.__createMockHost(fakeOutput)
        wlb = WorkloadBalancing()
        self.assertTrue(wlb.hostFeatureFlagValue(host))

    def testHostFeatureFlagFoundAndFalse(self):
        fakeOutput = """
               restrict_email_alerting: false
       restrict_historical_performance: false
                          restrict_wlb: false
                         restrict_rbac: false
                          restrict_dmc: false"""
        host = self.__createMockHost(fakeOutput)
        wlb = WorkloadBalancing()
        self.assertFalse(wlb.hostFeatureFlagValue(host))

    def testHostFeatureFlagNotPresent(self):
        fakeOutput = """
               restrict_email_alerting: false
       restrict_historical_performance: false
                          restrict_fish: true
                         restrict_rbac: false
                          restrict_dmc: false"""
        host = self.__createMockHost(fakeOutput)
        wlb = WorkloadBalancing()
        self.assertFalse(wlb.hostFeatureFlagValue(host))


class TestLicencedPoolFeatureFlags(XenRTUnitTestCase):

    def __createMockPool(self, fakeOutput):
        pool = Mock()
        pool.getPoolParam = Mock(return_value=fakeOutput)
        return pool

    def testPoolFeatureFlagFoundAndTrue(self):
        fakeOutput = """restrict_gpu: false; restrict_dr: false; restrict_vif_locking: false; restrict_storage_xen_motion: false; restrict_vgpu: true"""
        host = self.__createMockPool(fakeOutput)
        vgpu = VirtualGPU()
        self.assertTrue(vgpu.poolFeatureFlagValue(host))

    def testPoolFeatureFlagFoundAndFalse(self):
        fakeOutput = """restrict_gpu: false; restrict_dr: false; restrict_vif_locking: false; restrict_storage_xen_motion: false; restrict_vgpu: false"""
        host = self.__createMockPool(fakeOutput)
        vgpu = VirtualGPU()
        self.assertFalse(vgpu.poolFeatureFlagValue(host))

    def testPoolFeatureFlagNotPresent(self):
        fakeOutput = """restrict_gpu: false; restrict_dr: false; restrict_vif_locking: false; restrict_storage_xen_motion: false"""
        host = self.__createMockPool(fakeOutput)
        vgpu = VirtualGPU()
        self.assertFalse(vgpu.poolFeatureFlagValue(host))


class TestReadCachingEnablement(XenRTUnitTestCase):

    __TAP_CTRL_LIST = """pid=%s minor=%s state=0 args=vhd:/dev/VG_XenStorage-blah-blah"""
    __STAT_CMD = "tap-ctl stats -p %s -m %s"

    def __createMockHost(self, dataList):

        tapList = []
        calls = {}
        for pid, minor, statOutput in dataList:
            tapList.append(self.__TAP_CTRL_LIST % (pid, minor))
            calls[self.__STAT_CMD % (pid, minor)] = statOutput

        calls["tap-ctl list | cat"] = '\n'.join(tapList)
        host = Mock()
        host.execdom0 = Mock()
        host.execdom0.side_effect = lambda x: calls[x]
        return host

    def testTapCtlWithNoData(self):
        host = self.__createMockHost([])
        rc = ReadCaching()
        self.assertEqual([], rc.isEnabled(host))

    def testTapCtlWithNoRelevantData(self):
        host = self.__createMockHost([("1", "2", """{"nbd_mirror_failed": 0, "reqs_oustanding": 0}""")])
        rc = ReadCaching()
        self.assertEqual([False], rc.isEnabled(host))

    def testTapCtlWithExpectedOutputNoReadCache(self):
        data = [("1", "2", """{"reqs_oustanding": 0, "read_caching": "false" }"""),
                ("2", "3", """{"reqs_oustanding": 0, "read_caching": "false" }""")]
        host = self.__createMockHost(data)
        rc = ReadCaching()
        self.assertEqual([False, False], rc.isEnabled(host))

    def testTapCtlWithExpectedOutputReadCachePartial(self):
        data = [("1", "2", """{"reqs_oustanding": 0, "read_caching": "false" }"""),
                ("2", "3", """{"reqs_oustanding": 0, "read_caching": "true" }""")]
        host = self.__createMockHost(data)
        rc = ReadCaching()
        self.assertEqual([False, True], rc.isEnabled(host))

    def testTapCtlWithExpectedOutputReadCacheEnabled(self):
        data = [("1", "2", """{"reqs_oustanding": 0, "read_caching": "true" }"""),
                ("2", "3", """{"reqs_oustanding": 0, "read_caching": "true" }""")]
        host = self.__createMockHost(data)
        rc = ReadCaching()
        self.assertEqual([True, True], rc.isEnabled(host))


class FFHostDouble(object):
    CREEDENCE = "Creedence"

    def __init__(self, ver):
        self.productVersion = ver


class TestLicencedFeatureFactoryForCreedence(XenRTUnitTestCase):

    def testReturningAllFeaturesLength(self):
        fac = LicensedFeatureFactory()
        host = FFHostDouble(FFHostDouble.CREEDENCE)
        self.assertEqual(6, len(fac.allFeatures(host)))

    def testKeysAreNotNone(self):
        fac = LicensedFeatureFactory()
        host = FFHostDouble(FFHostDouble.CREEDENCE)
        [self.assertFalse(not i) for i in fac.allFeatures(host).keys()]
