from testing import XenRTUnitTestCase
from mock import Mock
import xenrt


class TestNFSStorageRepository(XenRTUnitTestCase):
    def testCreateStoresDeviceConfiguration(self):
        host = Mock()
        xenrt.TEC = Mock()
        xenrt.GEC = Mock()
        sr = xenrt.lib.xenserver.NFSStorageRepository(host, 'sr-name')

        sr.create('guest-IP', '/nfs-export')

        self.assertEquals(
            {
                'server': 'guest-IP',
                'serverpath': '/nfs-export'
            },
            sr.dconf
        )


class TestNFSv4StorageRepository(XenRTUnitTestCase):
    def testCreateUsesVersion4AsAParameter(self):
        host = Mock()
        xenrt.TEC = Mock()
        xenrt.GEC = Mock()
        sr = xenrt.lib.xenserver.NFSv4StorageRepository(host, 'sr-name')

        sr.create('guest-IP', '/nfs-export')

        self.assertEquals(
            {
                'server': 'guest-IP',
                'serverpath': '/nfs-export',
                'nfsversion': '4'
            },
            sr.dconf
        )

