from xenrt.lib.xenserver.licensedfeatures import WorkloadBalancing, ReadCaching, VirtualGPU, Hotfixing, ExportPoolResourceList
from testing import XenRTUnitTestCase
from mock import Mock


class TestLicencedFeatures(XenRTUnitTestCase):

    __UI_FEATURES = [Hotfixing(), ExportPoolResourceList(), WorkloadBalancing()]
    __SERVER_SIDE_FEATURES = [ReadCaching(), VirtualGPU()]

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
    def __createMockHost(self, fakeOutput):
        host = Mock()
        host.execdom0 = Mock(return_value=fakeOutput)
        return host

    def testTapCtlWithNoData(self):
        host = self.__createMockHost("")
        rc = ReadCaching()
        self.assertFalse(rc.isEnabled(host))

    def testTapCtlWithNoRelevantData(self):
        host = self.__createMockHost("""{"nbd_mirror_failed": 0, "reqs_oustanding": 0}""")
        rc = ReadCaching()
        self.assertFalse(rc.isEnabled(host))

    def testTapCtlWithExpectedOutputNoReadCache(self):
        fakeOutput = """{ "name": "vhd:/var/run/sr-mount/0c1bdf63-a87e-99d2-8646-654203ad2adf/473963eb-f87a-4f46-9a1e-1ab74a164f7f.vhd", "secs": [ 1088, 0 ], "images": [ { "name": "/var/run/sr-mount/0c1bdf63-a87e-99d2-8646-654203ad2adf/473963eb-f87a-4f46-9a1e-1ab74a164f7f.vhd", "hits": [ 1088, 0 ], "fail": [ 0, 0 ], "driver": { "type": 4, "name": "vhd", "status": null } } ], "tap": { "minor": 4, "reqs": [ 15, 15 ], "kicks": [ 13, 11 ] }, "xenbus": { "pool": "td-xenio-default", "domid": 4, "devid": 51728, "reqs": [ 65, 65 ], "kicks": [ 66, 65 ], "errors": { "msg": 0, "map": 0, "vbd": 0, "img": 0 } }, "FIXME_enospc_redirect_count": 0, "nbd_mirror_failed": 0, "reqs_oustanding": 0, "read_caching": "false" }"""
        host = self.__createMockHost(fakeOutput)
        rc = ReadCaching()
        self.assertFalse(rc.isEnabled(host))

    def testTapCtlWithExpectedOutputWithReadCache(self):
        fakeOutput = """{ "name": "vhd:/var/run/sr-mount/0c1bdf63-a87e-99d2-8646-654203ad2adf/473963eb-f87a-4f46-9a1e-1ab74a164f7f.vhd", "secs": [ 1088, 0 ], "images": [ { "name": "/var/run/sr-mount/0c1bdf63-a87e-99d2-8646-654203ad2adf/473963eb-f87a-4f46-9a1e-1ab74a164f7f.vhd", "hits": [ 1088, 0 ], "fail": [ 0, 0 ], "driver": { "type": 4, "name": "vhd", "status": null } } ], "tap": { "minor": 4, "reqs": [ 15, 15 ], "kicks": [ 13, 11 ] }, "xenbus": { "pool": "td-xenio-default", "domid": 4, "devid": 51728, "reqs": [ 65, 65 ], "kicks": [ 66, 65 ], "errors": { "msg": 0, "map": 0, "vbd": 0, "img": 0 } }, "FIXME_enospc_redirect_count": 0, "nbd_mirror_failed": 0, "reqs_oustanding": 0, "read_caching": "true" }"""
        host = self.__createMockHost(fakeOutput)
        rc = ReadCaching()
        self.assertTrue(rc.isEnabled(host))