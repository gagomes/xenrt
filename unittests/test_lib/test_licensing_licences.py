from testing import XenRTUnitTestCase
from xenrt.lib.xenserver.licensing import XenServerLicenceFactory

class HostDouble(object):
    def __init__(self, productVersion):
        self.productVersion = productVersion


class TestLicenceFactory(XenRTUnitTestCase):

    def testFactoryReturnsCorrectType(self):
        f = XenServerLicenceFactory()
        for t in ["Creedence", "TaMpA", "CLEARWATER"]:
            self.assertTrue(str(type(f.licence(HostDouble(t), "sku"))), "Licence")

    def testFactoryThrowsExceptionForUnknowType(self):
        f = XenServerLicenceFactory()
        self.assertRaises(ValueError, f.licence, HostDouble("SDFsdfSDFSDF"), "sku")
