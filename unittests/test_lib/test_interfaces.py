from testing import XenRTTestCaseUnitTestCase
import xenrt.lib.cloud
import xenrt.lib.xl
from zope.interface.verify import verifyObject
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
        verifyObject(xenrt.Toolstack, c)

    def test_xlInterface(self):
        """Verify the XLToolstack class implements the Toolstack interface"""
        x = xenrt.lib.xl.XLToolstack()
        verifyObject(xenrt.Toolstack, x)

    def test_instanceInterface(self):
        """Verify the Instance class implements the OSParent interface"""
        i = InstanceTest()
        verifyObject(xenrt.OSParent, i)
