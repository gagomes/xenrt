"""
General helper code for unit testing framework
"""

import unittest
from mock import patch, Mock

class XenRTUnitTestCase(unittest.TestCase):
    """
    Abstraction of the unittest.TestCase class to add any additional functionality
    """

    def run_for_many(self, listOfData, functionPointer):
        """
        @param listOfData: data to run the provided lambda over
        @type listOfData: list
        @param functionPointer: a test to run on each list item
        @type functionPointer: lambda 
        """
        [functionPointer(data) for data in listOfData]


class XenRTTestCaseUnitTestCase(XenRTUnitTestCase):
    def setUp(self):
        try:
            self.tecPatcher = patch("xenrt.TEC")
            self.gecPatcher = patch("xenrt.GEC")
            self.regPatcher = patch("xenrt.registry")
            self.ldriPatcher = patch("xenrt.resources.LocalDirectoryResourceImplementer")
            self.hostPatcher = patch("xenrt.host")
            self.guestPatcher = patch("xenrt.guest")

            self.gec = self.gecPatcher.start()
            self.tec = self.tecPatcher.start()
            self.reg = self.regPatcher.start()
            self.ldri = self.ldriPatcher.start()
            self.ldri.return_value._exists.return_value = True

        except:
            self.tearDown()
            raise
   
    def _createHost(self):
        host = Mock()
        host.execdom0 = Mock(return_value=None)
        return host


    def tearDown(self):
        for p in [self.gecPatcher, self.tecPatcher, self.regPatcher, 
                  self.ldriPatcher, self.hostPatcher, self.guestPatcher]:
            try:
                p.stop()
            except:
                pass
        
        
