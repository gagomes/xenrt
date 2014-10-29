from xenrt.lib.xenserver.licencedfeatures import WorkloadBalancing, ReadCaching, VirtualGPU, Hotfixing, ExportPoolResourceList
from testing import XenRTUnitTestCase


class TestLicencedFeatures(XenRTUnitTestCase):

    __UI_FEATURES = [Hotfixing(), ExportPoolResourceList()]
    __SERVER_SIDE_FEATURES = [WorkloadBalancing(), ReadCaching(), VirtualGPU()]

    def testUIFlaggableStatesIndicateEnableCannotBeChecked(self):
        for feature in self.__UI_FEATURES:
            self.assertFalse(feature.stateCanBeChecked)

    def testServerSideFlaggableStatesIndicateEnableCanBeChecked(self):
        for feature in self.__SERVER_SIDE_FEATURES:
            self.assertTrue(feature.stateCanBeChecked)

    def testUIFeaturesIsEnabledThrows(self):
        for feature in self.__UI_FEATURES:
            self.assertRaises(NotImplementedError, feature.isEnabled)
