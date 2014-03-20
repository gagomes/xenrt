from testing import XenRTTestCaseUnitTestCase
import xenrt.lib.cloud
import xenrt.lib.xl
import xenrt.lib.opsys
from zope.interface.verify import verifyObject, verifyClass
from zope.interface import implementedBy
from mock import Mock

class TestInterfaces(XenRTTestCaseUnitTestCase):
    def test_cloudstackInterface(self):
        """Verify that the CloudStack class implements the Toolstack interface"""

        # Mock out the classes used by the CloudStack __init__ so they don't get created
        xenrt.lib.cloud.ManagementServer = Mock()
        xenrt.lib.cloud.MarvinApi = Mock()
        # Create the CloudStack object, mocking place
        c = xenrt.lib.cloud.CloudStack(place = Mock())

        # Do the verification
        verifyObject(xenrt.interfaces.Toolstack, c)

    def test_xlInterface(self):
        """Verify the XLToolstack class implements the Toolstack interface"""
        # Create the toolstack object, no mocking needed for now
        x = xenrt.lib.xl.XLToolstack()
        # Do the verification
        verifyObject(xenrt.interfaces.Toolstack, x)

    def test_instanceInterface(self):
        """Verify the Instance class implements the OSParent interface"""
        # Mock out the methods used by the Instance __init__ so they don't get called
        xenrt.lib.opsys.osFactory = Mock()
        # Crete the Instance, mocking toolstack
        i = xenrt.lib.generic.Instance(Mock(), None, None, None, None)
        # Do the verification
        verifyObject(xenrt.interfaces.OSParent, i)

def test_osLibraries():
    """Generate tests for each known OS library"""

    # Some of the libraries call xenrt.TEC().lookup, so we need to mock xenrt.TEC
    xenrt.TEC = Mock()

    def oslib_test(oslib):
        # Instantiate the OS library
        o = oslib.testInit()
        # Verify all interfaces declared as being implemented
        for i in list(implementedBy(oslib)):
            verifyObject(i, o)

    def oslib_supportedInstallMethods(oslib):
        # Instantiate the OS library
        o = oslib.testInit()

        implementedInterfaces = list(implementedBy(oslib))

        # Determine what interfaces are required based on the supportedInstallMethods attribute
        requiredInterfaces = filter(lambda i: o._allInstallMethods[i] in o.supportedInstallMethods, o._allInstallMethods)

        # Verify the required interfaces are implemented
        for i in requiredInterfaces:
            if not i in implementedInterfaces:
                raise AssertionError("Interface %s not implemented but stated in supportedInstallMethods" % i.__name__)

    for l in xenrt.lib.opsys.oslist:
        # We use lambda functions here so we can give them a unique description
        testfn = lambda: oslib_test(l)
        testfn.description = "Verify the %s class implements its interfaces" % l.__name__
        yield testfn
        testfn = lambda: oslib_supportedInstallMethods(l)
        testfn.description = "Verify the %s class implements interfaces for all supportedInstallMethods" % l.__name__
        yield testfn
