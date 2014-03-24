"""
General helper code for unit testing framework
"""

import unittest
from mock import patch, Mock
from nose.plugins.attrib import attr
from nose.plugins.skip import SkipTest
from functools import wraps
import types
from zope.interface import classImplements
import sys

"""
Helper methods
"""

def wip(fn):
    """
    Work-in-progress decorator @wip
    This decorator lets you check tests into version control and not gate a push 
    while allowing you to work on making them pass
     - If the test fails it will be skipped
     - If the test passes it will report a failure
    """
    @wraps(fn)
    def run_test(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception as ex:
            raise SkipTest( "WIP FAILURE: %s" % str(ex))
        raise AssertionError("Test passed but is work in progress")

    return attr('wip')(run_test)

_interfaceMockClasses = {}
def interfaceMock(interfaceClass):
    if _interfaceMockClasses.has_key(interfaceClass):
        return _interfaceMockClasses[interfaceClass]()

    return _createInterfaceMock(interfaceClass)()

def _createInterfaceMock(interfaceClass):
    """Dynamically create a Mock sub class that implements the given zope.interface"""

    # the init method, automatically specifying the interface methods
    def init(self, *args, **kwargs):
        Mock.__init__(self, spec=interfaceClass.names(),
                      *args, **kwargs)

    # we derive the sub class name from the interface name
    name = interfaceClass.__name__ + "Mock"
    sys.stderr.write("Mocking %s\n" % name)

    # create the class object and provide the init method
    mockClass = types.TypeType(name, (Mock, ), {"__init__": init})

    # the new class should implement the interface
    classImplements(mockClass, interfaceClass)

    _interfaceMockClasses[interfaceClass] = mockClass
    return mockClass

"""
Unittest abstraction for XenRT
"""
class XenRTBaseTestCase(unittest.TestCase):
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


"""
Implementations of the XenRT unit testing abstraction marked with attributes
You can run these with the nose runner by adding a '-a <attr name>'
"""

@attr("UnitTest")
class XenRTUnitTestCase(XenRTBaseTestCase): pass

@attr("IntegrationTest")
class XenRTIntegrationTestCase(XenRTBaseTestCase): pass

@attr("TCTest")
class XenRTTestCaseUnitTestCase(XenRTUnitTestCase):
    """
    Protoype code - what is required to quickly implement a unit test for a xenrt TestCase
    """
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

