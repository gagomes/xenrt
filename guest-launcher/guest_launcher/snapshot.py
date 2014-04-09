import logging
import re
import time

from guest_launcher import executor
from guest_launcher import guest
from guest_launcher import vm_snapshot


log = logging.getLogger(__name__)


def create_snapshotter(hypervisor, executor):
    factories = [VirtualBoxBasedSnapshotterFactory(executor)]

    for factory in factories:
        snapshotter = factory.create_snapshotter(hypervisor)
        if snapshotter:
            return snapshotter


class VirtualBoxBasedSnapshotterFactory(object):
    def __init__(self, executor):
        self.executor = executor

    def create_snapshotter(self, url):
        starter = vm_snapshot.url_to_vm_snapshot_based(
            url, VirtualBoxBasedSnapshotter)
        if starter:
            starter.hosted_guest = guest.VirtualBoxHostedGuest(
                starter.vm_name, self.executor)
            return starter


class VirtualBoxBasedSnapshotter(vm_snapshot.VMSnapShotParty):
    def __init__(self, vm_name, snapshot_name):
        super(VirtualBoxBasedSnapshotter, self).__init__(
            vm_name, snapshot_name)
        self.hosted_guest = None

    def snap(self):
        self.hosted_guest.snap(self.snapshot_name)
