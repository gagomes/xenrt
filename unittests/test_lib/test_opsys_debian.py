from testing import XenRTUnitTestCase, interfaceMock
import xenrt
from xenrt.lib.opsys.debian import DebianLinux, UbuntuLinux

class TestDebianLinuxOverrides(XenRTUnitTestCase):
    
    def setUp(self):
        self.parent = interfaceMock(xenrt.interfaces.OSParent)

    def testKnownDistroOverride(self):
        """
        Given a string representing a distro, When the class is asked if it is supported, Then expect only debian based distros to return true
        """
        data = { ("debian", True),  ("debianWho", True), ("WhoIsdebian", False), 
                ("Debian", False), ("ubuntu", False), ("CatInATree", False) }
        self.run_for_many(data, self.__testKnownDistroOverride)

    def __testKnownDistroOverride(self, data):
        distro, exepcted = data
        self.assertEqual(exepcted, DebianLinux.knownDistro(distro))
    
    def testIsoNameImplementation(self):
        """Given a debain distro name, When the ISO name is requested, Then expect the name to be converted"""
        data={("debian60_x86-32", "deb6_x86-32_xenrtinst.iso"), ("debian70_x86-64", "deb7_x86-64_xenrtinst.iso"),
              ("debian60", "deb6_x86-64_xenrtinst.iso"), ("bobbins", None)}
        self.run_for_many(data, self.__testIsoNameImplementation)

    def __testIsoNameImplementation(self, data):
       distro, expectedIso = data
       dl = DebianLinux(distro, self.parent)
       self.assertEqual(expectedIso, dl.isoName)

    def testDebianNameConversion(self):
        """Given a debian distro, When the release name is requested, Then expect the a string representing the release"""
        data = {("debian60", "squeeze"), ("debian70", "wheezy"), ("ScoobyDoo", None),
                ("Debian60", None), ("debian6", None)}
        self.run_for_many(data, self.__testDebianNameConversion)
    
    def __testDebianNameConversion(self, data):
        distro, expected = data
        dl = DebianLinux(distro, self.parent)
        self.assertEqual(expected, dl.debianName)


class TestUbuntuLinuxOverrides(XenRTUnitTestCase):
    
    def setUp(self):
        self.parent = interfaceMock(xenrt.interfaces.OSParent)

    def testKnownDistroOverride(self):
        """
        Given a string representing a distro, When the class is asked if it is supported, Then expect only ubuntu based distros to return true
        """
        data = { ("ubuntu", True),  ("ubuntuWho", True), ("WhoIsubuntu", False), 
                ("Ubuntu", False), ("ubuntu1004", True), ("CatInATree", False) }
        self.run_for_many(data, self.__testKnownDistroOverride)

    def __testKnownDistroOverride(self, data):
        distro, exepcted = data
        self.assertEqual(exepcted, UbuntuLinux.knownDistro(distro))
    
    def testIsoNameImplementation(self):
        """Given a ubuntu distro name, When the ISO name is requested, Then expect the name to be converted"""
        data={("ubuntu1004_x86-32", "ubuntu1004_x86-32_xenrtinst.iso"), 
              ("ubuntu1204_x86-64", "ubuntu1204_x86-64_xenrtinst.iso"),
              ("ubuntu1004", "ubuntu1004_x86-64_xenrtinst.iso"), 
              ("ubuntu1404", "ubuntu1404_x86-64_xenrtinst.iso")}
        self.run_for_many(data, self.__testIsoNameImplementation)

    def __testIsoNameImplementation(self, data):
       distro, expectedIso = data
       dl = UbuntuLinux(distro, self.parent)
       self.assertEqual(expectedIso, dl.isoName)

    def testUbuntuNameConversion(self):
        """Given a ubuntu distro, When the release name is requested, Then expect the a string representing the release"""
        data = {("ubuntu1004", "lucid"), ("ubuntu1204", "precise"), ("ScoobyDoo", None),
                ("Ubuntu1004", None), ("ubuntu", None), ("ubuntu1404", "trusty")}
        self.run_for_many(data, self.__testUbuntuNameConversion)
    
    def __testUbuntuNameConversion(self, data):
        distro, expected = data
        dl = UbuntuLinux(distro, self.parent)
        self.assertEqual(expected, dl.debianName)


