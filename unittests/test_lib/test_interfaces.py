from testing import XenRTTestCaseUnitTestCase
import xenrt.lib.cloud
import xenrt.lib.xl
import xenrt.lib.opsys
from zope.interface.verify import verifyObject, verifyClass
from zope.interface import implementedBy
from mock import Mock

class CloudStackTest(xenrt.lib.cloud.CloudStack):
    """Mock Cloudstack class that overrides __init__ so we can just check the interface"""
    def __init__(self):
        pass

class InstanceTest(xenrt.lib.generic.Instance):
    """Mock instance class that overrides __init__ so we can just check the interface"""
    def __init__(self):
        self.name=None
        self.toolstack = Mock()
        self.toolstack.instanceHypervisorType = Mock() # The hypervisorType property needs to call this, so we need to mock it

class TestInterfaces(XenRTTestCaseUnitTestCase):
    def test_cloudstackInterface(self):
        """Verify that the CloudStack class implements the Toolstack interface"""
        c = CloudStackTest()
        verifyObject(xenrt.interfaces.Toolstack, c)

    def test_xlInterface(self):
        """Verify the XLToolstack class implements the Toolstack interface"""
        x = xenrt.lib.xl.XLToolstack()
        verifyObject(xenrt.interfaces.Toolstack, x)

    def test_instanceInterface(self):
        """Verify the Instance class implements the OSParent interface"""
        i = InstanceTest()
        verifyObject(xenrt.interfaces.OSParent, i)

def test_osLibraries():

    # Some of the libraries call xenrt.TEC().lookup, so we need to mock xenrt.TEC
    xenrt.TEC = Mock()

    def oslib_test(oslib):
        o = oslib.testInit()
        for i in list(implementedBy(oslib)):
            verifyObject(i, o)

    def oslib_supportedInstallMethods(oslib):
        o = oslib.testInit()
        implementedInterfaces = list(implementedBy(oslib))
        requiredInterfaces = filter(lambda i: o._allInstallMethods[i] in o.supportedInstallMethods, o._allInstallMethods)
        for i in requiredInterfaces:
            if not i in implementedInterfaces:
                raise AssertionError("Interface %s not implemented but stated in supportedInstallMethods" % i.__name__)

    for l in xenrt.lib.opsys.oslist:
        testfn = lambda: oslib_test(l)
        testfn.description = "Verify the %s class implements its interfaces" % l.__name__
        yield testfn
        testfn = lambda: oslib_supportedInstallMethods(l)
        testfn.description = "Verify the %s class implements interfaces for all supportedInstallMethods" % l.__name__
        yield testfn
