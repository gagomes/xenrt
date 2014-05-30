import unittest

from guest_launcher import guest_starter


class TestVirtualBoxbasedGuestStarterFactory(unittest.TestCase):
    def test_well_formed_url_recognised(self):
        factory = guest_starter.VirtualBoxBasedGuestStarterFactory(None)

        result = factory.create_guest_starter(
            'virtualbox-pfwd:127.0.0.1:wendows/test')

        self.assertTrue(result is not None)

    def test_well_formed_url_creates_starter_with_params(self):
        factory = guest_starter.VirtualBoxBasedGuestStarterFactory(None)

        starter = factory.create_guest_starter(
            'virtualbox-pfwd:192.168.1.2:wendows/test')

        self.assertEquals('wendows', starter.vm_name)
        self.assertEquals('test', starter.snapshot_name)
        self.assertEquals('192.168.1.2', starter.ports_forwarded_to)


class TestXenServerBasedGuestStarterFactory(unittest.TestCase):
    def test_well_formed_url_recognised(self):
        factory = guest_starter.XenServerBasedGuestStarterFactory(None)

        result = factory.create_guest_starter(
            'xenserver:root@host:password:vmname/snapname')

        self.assertTrue(result is not None)

    def test_url_with_spaces_is_recognised(self):
        factory = guest_starter.XenServerBasedGuestStarterFactory(None)

        result = factory.create_guest_starter(
            'xenserver:root@host:password:vmname with spaces/snapname')

        self.assertTrue(result is not None)

    def test_well_formed_url_creates_starter_with_proper_params(self):
        factory = guest_starter.XenServerBasedGuestStarterFactory('executor')

        starter = factory.create_guest_starter(
            'xenserver:root@host:password:vmname/snapname')

        self.assertEquals('vmname', starter.vm_name)
        self.assertEquals('snapname', starter.snapshot_name)

    def test_executor_is_decorated_and_params_set_on_decorator(self):
        factory = guest_starter.XenServerBasedGuestStarterFactory('executor')

        starter = factory.create_guest_starter(
            'xenserver:root@host:password:vmname/snapname')

        self.assertEquals('executor', starter.executor.decorated_executor)
        self.assertEquals('root', starter.executor.username)
        self.assertEquals('host', starter.executor.host)
        self.assertEquals('password', starter.executor.password)


class TestCreateGuestStarter(unittest.TestCase):
    def test_created_object_has_executor(self):
        obj = guest_starter.create_guest_starter(
            'virtualbox-pfwd:127.0.0.1:windows/t', 'executor')

        self.assertEquals(
            'executor', obj.executor)

    def test_creating_a_xenserver_starter(self):
        obj = guest_starter.create_guest_starter(
            'xenserver:root@host:password:vmname/snapname', 'executor')

        self.assertTrue(obj is not None)
