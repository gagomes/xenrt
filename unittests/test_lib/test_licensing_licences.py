from testing import XenRTUnitTestCase
from xenrt.lib.xenserver.licensing import XenServerLicenceFactory

class HostDouble(object):
    def __init__(self, productVersion):
        self.productVersion = productVersion


class TestLicenceFactoryLicenceForSKU(XenRTUnitTestCase):

    def testFactoryReturnsCorrectType(self):
        f = XenServerLicenceFactory()
        for t in ["Creedence", "TaMpA", "CLEARWATER"]:
            self.assertTrue(str(type(f.licence(HostDouble(t), "sku"))), "Licence")

    def testFactoryThrowsExceptionForUnknowType(self):
        f = XenServerLicenceFactory()
        self.assertRaises(ValueError, f.licence, HostDouble("SDFsdfSDFSDF"), "sku")


class TestLicenceFactoryAllLicenceForHost(XenRTUnitTestCase):

    def testFactoryReturnsCorrectAmount(self):
        f = XenServerLicenceFactory()
        for t, c in [("Creedence", 7)]:
            self.assertEqual(c, len(f.allLicences(HostDouble(t))))

    def testFactoryThrowsExceptionForUnknowType(self):
        f = XenServerLicenceFactory()
        for t in ["tampa", "Clearwater"]:
            self.assertRaises(ValueError, f.allLicences, HostDouble(t))


class TestLicenceFactoryXSOnlyLicenceForHost(XenRTUnitTestCase):

    def testFactoryReturnsCorrectAmount(self):
        f = XenServerLicenceFactory()
        for t, c in [("Creedence", 3)]:
            self.assertEqual(c, len(f.xenserverOnlyLicences(HostDouble(t))))

    def testFactoryThrowsExceptionForUnknowType(self):
        f = XenServerLicenceFactory()
        for t in ["tampa", "Clearwater"]:
            self.assertRaises(ValueError, f.xenserverOnlyLicences, HostDouble(t))
