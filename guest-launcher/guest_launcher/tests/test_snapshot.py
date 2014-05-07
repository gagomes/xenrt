import unittest
import mock

from guest_launcher import executor
from guest_launcher import snapshot
from guest_launcher import guest


class TestVirtualBoxBasedSnapshotterFactory(unittest.TestCase):
    def test_unrecognised_url_returns_None(self):
        factory = snapshot.VirtualBoxBasedSnapshotterFactory(None)

        snapshotter = factory.create_snapshotter('non-virtualbox-url')

        self.assertTrue(snapshotter is None)

    def test_well_formed_url_recognised(self):
        factory = snapshot.VirtualBoxBasedSnapshotterFactory(None)

        snapshotter = factory.create_snapshotter('virtualbox:wendows/test')

        self.assertTrue(snapshotter is not None)

    def test_well_formed_url_creates_starter_with_params(self):
        factory = snapshot.VirtualBoxBasedSnapshotterFactory(None)

        snapshotter = factory.create_snapshotter('virtualbox:wendows/test')

        self.assertEquals('wendows', snapshotter.vm_name)
        self.assertEquals('test', snapshotter.snapshot_name)

    def test_created_object_has_configured_hosted_guest(self):
        factory = snapshot.VirtualBoxBasedSnapshotterFactory('executor')

        snapshotter = factory.create_snapshotter('virtualbox:wendows/test')
        hosted_guest = snapshotter.hosted_guest

        self.assertEquals('wendows', hosted_guest.vm_name)
        self.assertEquals('executor', hosted_guest.executor)


class TestVirtualBoxBasedSnapshotter(unittest.TestCase):
    def test_snap_calls_snap_on_hosted_guest(self):
        snapshotter = snapshot.VirtualBoxBasedSnapshotter(
            'vm_name', 'snap_name')
        hosted_guest = snapshotter.hosted_guest = mock.Mock(
            spec=guest.VirtualBoxHostedGuest)

        snapshotter.snap()

        hosted_guest.snap.assert_called_once_with('snap_name')


class TestCreateSnapshotter(unittest.TestCase):
    def test_virtualbox_url_recognised(self):
        snapshotter = snapshot.create_snapshotter('virtualbox:a/b', 'executor')

        self.assertEquals('executor', snapshotter.hosted_guest.executor)
