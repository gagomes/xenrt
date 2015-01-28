from testing import XenRTUnitTestCase
import os
from xenrt.lib.xenserver import guest
from PIL import Image
from mock import Mock, patch, PropertyMock
import xenrt


def pathForDataFile(fname):
    thisFile = __file__
    thisDir = os.path.dirname(thisFile)
    dataDir = os.path.join(thisDir, '..', 'data')
    return os.path.abspath(os.path.join(dataDir, fname))


class TestIsBSODBlue(XenRTUnitTestCase):

    def testWindows7BSODisBSODBlue(self):
        screenshot = pathForDataFile('bsod-win7.jpg')
        i = Image.open(screenshot)

        self.assertTrue(guest.isBSODBlue(i))

    def testWindows8BSODisBSODBlue(self):
        screenshot = pathForDataFile('bsod-win8.jpg')
        i = Image.open(screenshot)

        self.assertTrue(guest.isBSODBlue(i))

    def testWindows03FullDesktopIsNotBSODBlue(self):
        screenshot = pathForDataFile('win03-desktop-full.jpg')
        i = Image.open(screenshot)

        self.assertFalse(guest.isBSODBlue(i))

    def testWindows08FullDesktopIsNotBSODBlue(self):
        screenshot = pathForDataFile('win8-desktop-full.jpg')
        i = Image.open(screenshot)

        self.assertFalse(guest.isBSODBlue(i))

class TestMaxSupportedVCPU(XenRTUnitTestCase):

    conf = None

    @classmethod
    def setUpClass(cls):
        cls.conf = xenrt.Config().config

    def __lookup(self, kw, *args):
        if type(kw) == type(""):
            return self.conf[kw]
        tmp = self.conf
        for key in kw:
           tmp = tmp[key]

        return tmp

    @patch("xenrt.TEC")
    @patch("xenrt.GEC")
    def __run(self, args, gec, tec):
        guest = xenrt.lib.xenserver.guest.TampaGuest("Guest")
        tec.return_value.lookup = self.__lookup
        tec.return_value.lookupHost = Mock(return_value = None)
        distro, arch, result = args
        guest.distro = distro
        guest.arch = arch
        if distro.startswith("w") or distro.startswith("vista"):
            guest.windows = True
        else:
            guest.windows = False
        self.assertTrue(guest.getMaxSupportedVCPUCount() == result)
        
    def __testCreedence(self, args):
        self.conf["PRODUCT_VERSION"] = "Creedence"
        self.__run(args)

    def __testTampa(self, args):
        self.conf["PRODUCT_VERSION"] = "Tampa"
        self.__run(args)

    def __testClearwater(self, args):
        self.conf["PRODUCT_VERSION"] = "Clearwater"
        self.__run(args)

    def __testDundee(self, args):
        self.conf["PRODUCT_VERSION"] = "Dundee"
        self.__run(args)

    def testCreedenceRHEL(self):
        distros = ["rhel61", "rhel61", "rhel7"]
        archs = ["x86", "x86-64", "x86-64"]
        results = [32, 32, 16]

        self.run_for_many(zip(distros, archs, results), self.__testCreedence)

    def testCreedenceDeb(self):
        distros = ["deb6", "deb6", "deb7", "deb7"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [32, 32, 32, 32]

        self.run_for_many(zip(distros, archs, results), self.__testCreedence)

    def testCreedenceUbuntu(self):
        distros = ["ubuntu1204", "ubuntu1204", "ubuntu1404", "ubuntu1404"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [8, 32, 8, 16]

        self.run_for_many(zip(distros, archs, results), self.__testCreedence)

    def testCreedenceWin(self):
        distros = ["w2k3eesp2pae", "winxpsp3", "ws08-x64", "win7-x86", "win81-x64", "ws08r2dcsp1-x64", "ws12-x64"]
        results = [4, 2, 8, 2, 2, 16, 16]

        self.run_for_many(zip(distros, ["x86"] * len(distros), results), self.__testCreedence)

    def testTampaRHEL(self):
        distros = ["rhel61", "rhel61", "rhel7"]
        archs = ["x86", "x86-64", "x86-64"]
        results = [16, 16, 16]

        self.run_for_many(zip(distros, archs, results), self.__testTampa)

    def testTampaDeb(self):
        distros = ["deb6", "deb6", "deb7", "deb7"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [16, 16, 16, 16]

        self.run_for_many(zip(distros, archs, results), self.__testTampa)

    def testTampaUbuntu(self):
        distros = ["ubuntu1204", "ubuntu1204", "ubuntu1404", "ubuntu1404"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [8, 16, 8, 16]

        self.run_for_many(zip(distros, archs, results), self.__testTampa)

    def testTampaWin(self):
        distros = ["w2k3eesp2pae", "winxpsp3", "ws08-x64", "win7-x86", "win81-x64", "ws08r2dcsp1-x64", "ws12-x64"]
        results = [4, 2, 8, 2, 2, 16, 16]

        self.run_for_many(zip(distros, ["x86"] * len(distros), results), self.__testTampa)

    def testClearwaterRHEL(self):
        distros = ["rhel61", "rhel61", "rhel7"]
        archs = ["x86", "x86-64", "x86-64"]
        results = [16, 16, 16]

        self.run_for_many(zip(distros, archs, results), self.__testClearwater)

    def testClearwaterDeb(self):
        distros = ["deb6", "deb6", "deb7", "deb7"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [16, 16, 16, 16]

        self.run_for_many(zip(distros, archs, results), self.__testClearwater)

    def testClearwaterUbuntu(self):
        distros = ["ubuntu1204", "ubuntu1204", "ubuntu1404", "ubuntu1404"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [8, 16, 8, 16]

        self.run_for_many(zip(distros, archs, results), self.__testClearwater)

    def testClearwaterWin(self):
        distros = ["w2k3eesp2pae", "winxpsp3", "ws08-x64", "win7-x86", "win81-x64", "ws08r2dcsp1-x64", "ws12-x64"]
        results = [4, 2, 8, 2, 2, 16, 16]

        self.run_for_many(zip(distros, ["x86"] * len(distros), results), self.__testClearwater)

    def testDundeeRHEL(self):
        distros = ["rhel61", "rhel61", "rhel7"]
        archs = ["x86", "x86-64", "x86-64"]
        results = [32, 32, 16]

        self.run_for_many(zip(distros, archs, results), self.__testDundee)

    def testDundeeDeb(self):
        distros = ["deb6", "deb6", "deb7", "deb7"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [32, 32, 32, 32]

        self.run_for_many(zip(distros, archs, results), self.__testDundee)

    def testDundeeUbuntu(self):
        distros = ["ubuntu1204", "ubuntu1204", "ubuntu1404", "ubuntu1404"]
        archs = ["x86", "x86-64", "x86", "x86-64"]
        results = [8, 32, 8, 16]

        self.run_for_many(zip(distros, archs, results), self.__testDundee)

    def testDundeeWin(self):
        distros = ["w2k3eesp2pae", "winxpsp3", "ws08-x64", "win7-x86", "win81-x64", "ws08r2dcsp1-x64", "ws12-x64"]
        results = [4, 2, 8, 2, 2, 16, 16]

        self.run_for_many(zip(distros, ["x86"] * len(distros), results), self.__testDundee)

