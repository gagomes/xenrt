from testing import XenRTUnitTestCase
import os
from xenrt.lib.xenserver import guest
from PIL import Image


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
