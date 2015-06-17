from testing import XenRTUnitTestCase, interfaceMock
import xenrt
from xenrt.lib.opsys.sles import SLESLinux 

class TestSLESLinuxOverrides(XenRTUnitTestCase):
    
    def setUp(self):
        self.parent = interfaceMock(xenrt.interfaces.OSParent)

    def testKnownDistroOverride(self):
        """
        Given a string representing a distro, When the class is asked if it is supported, 
        Then expect only SLES based distros to return true

        """
        data = { ("sles", True), ("sles11", True), ("centos", False), ("oel", False)} 
        self.run_for_many(data, self.__testKnownDistroOverride)

    def __testKnownDistroOverride(self, data):
        distro, exepcted = data
        self.assertEqual(exepcted, SLESLinux.knownDistro(distro))
    
    def testIsoNameImplementation(self):
        """Given a SLES distro name, When the ISO name is requested, Then expect the name to be converted"""

        data = {("sles10_x86-32", "sles10_x86-32_xenrtinst.iso"), 
                ("sles112_x86-64", "sles112_x86-64_xenrtinst.iso"), 
                ("sles11_x86-32", "sles11_x86-32_xenrtinst.iso"), 
                ("sles102_x86-64", "sles102_x86-64_xenrtinst.iso"), 
                ("hopkins", None)}

        self.run_for_many(data, self.__testIsoNameImplementation)

    def __testIsoNameImplementation(self, data):
       distro, expectedIso = data
       dl = SLESLinux(distro, self.parent)
       self.assertEqual(expectedIso, dl.isoName)


