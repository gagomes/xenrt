from testing import XenRTUnitTestCase, interfaceMock
import xenrt
from xenrt.lib.opsys.rhel import RHELLinux, CentOSLinux, OELLinux 

class TestRHELLinuxOverrides(XenRTUnitTestCase):
    
    def setUp(self):
        self.parent = interfaceMock(xenrt.interfaces.OSParent)

    def testKnownDistroOverride(self):
        """
        Given a string representing a distro, When the class is asked if it is supported, 
        Then expect only RHEL based distros to return true

        """
        data = { ("rhel", True), ("rhel6", True), ("centos", False), ("oel", False)} 
        self.run_for_many(data, self.__testKnownDistroOverride)

    def __testKnownDistroOverride(self, data):
        distro, exepcted = data
        self.assertEqual(exepcted, RHELLinux.knownDistro(distro))
    
    def testIsoNameImplementation(self):
        """Given a RHEL distro name, When the ISO name is requested, Then expect the name to be converted"""

        data = {("rhel38_x86-32", "rhel38_x86-32_xenrtinst.iso"), 
                ("rhel5_x86-64", "rhel5_x86-64_xenrtinst.iso"), 
                ("rhel6_x86-32", "rhel6_x86-32_xenrtinst.iso"), 
                ("rhel6_x86-64", "rhel6_x86-64_xenrtinst.iso"), 
                ("rhel65_x86-32", "rhel65_x86-32_xenrtinst.iso"), 
                ("rhel65_x86-64", "rhel65_x86-64_xenrtinst.iso"),
                ("hopkins", None)}

        self.run_for_many(data, self.__testIsoNameImplementation)

    def __testIsoNameImplementation(self, data):
       distro, expectedIso = data
       dl = RHELLinux(distro, self.parent)
       self.assertEqual(expectedIso, dl.isoName)

class TestCentOSLinuxOverrides(XenRTUnitTestCase):

    def setUp(self):
        self.parent = interfaceMock(xenrt.interfaces.OSParent)

    def testKnownDistroOverride(self):
        """
        Given a string representing a distro, When the class is asked if it is supported,
        Then expect only CentOS based distros to return true
        """

        data = { ("rhel", False), ("centos", True), ("centos6", True), ("oel", False)}
        self.run_for_many(data, self.__testKnownDistroOverride)

    def __testKnownDistroOverride(self, data):
        distro, exepcted = data
        self.assertEqual(exepcted, CentOSLinux.knownDistro(distro))

    def testIsoNameImplementation(self):
        """Given a CentOS distro name, When the ISO name is requested, Then expect the name to be converted"""

        data = {("centos43_x86-32", "centos43_x86-32_xenrtinst.iso"), 
                ("centos43_x86-64", "centos43_x86-64_xenrtinst.iso"), 
                ("centos6_x86-32", "centos6_x86-32_xenrtinst.iso"), 
                ("centos6_x86-64", "centos6_x86-64_xenrtinst.iso"), 
                ("centos65_x86-32", "centos65_x86-32_xenrtinst.iso"), 
                ("centos65_x86-64", "centos65_x86-64_xenrtinst.iso"), 
                ("prestige", None)}

        self.run_for_many(data, self.__testIsoNameImplementation)

    def __testIsoNameImplementation(self, data):
       distro, expectedIso = data
       dl = CentOSLinux(distro, self.parent)
       self.assertEqual(expectedIso, dl.isoName)

class TestOELLinuxOverrides(XenRTUnitTestCase):

    def setUp(self):
        self.parent = interfaceMock(xenrt.interfaces.OSParent)

    def testKnownDistroOverride(self):
        """
        Given a string representing a distro, When the class is asked if it is supported,
        Then expect only OEL based distros to return true
        """

        data = { ("rhel", False), ("centos", False), ("oel", True), ("oel6", True)}
        self.run_for_many(data, self.__testKnownDistroOverride)

    def __testKnownDistroOverride(self, data):
        distro, exepcted = data
        self.assertEqual(exepcted, OELLinux.knownDistro(distro))

    def testIsoNameImplementation(self):
        """Given a OEL distro name, When the ISO name is requested, Then expect the name to be converted"""

        data = {("oel510_x86-32", "oel510_x86-32_xenrtinst.iso"),
                ("oel6_x86-32", "oel6_x86-32_xenrtinst.iso"),
                ("oel6_x86-64", "oel6_x86-64_xenrtinst.iso"),
                ("oel65_x86-32", "oel65_x86-32_xenrtinst.iso"), 
                ("oel65_x86-64", "oel65_x86-64_xenrtinst.iso"),
                ("tiffael", None)}

        self.run_for_many(data, self.__testIsoNameImplementation)

    def __testIsoNameImplementation(self, data):
       distro, expectedIso = data
       dl = OELLinux(distro, self.parent)
       self.assertEqual(expectedIso, dl.isoName)

