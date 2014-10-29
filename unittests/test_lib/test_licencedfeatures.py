from xenrt.lib.xenserver.licencedfeatures import WorkloadBalancing, ReadCaching, VirtualGPU, Hotfixing, ExportPoolResourceList
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
            self.assertRaises(NotImplementedError, feature.isEnabled)


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