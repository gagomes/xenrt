import re

from guest_launcher import vm_snapshot
from guest_launcher import guest
from guest_launcher.executor import OverSSHExecutor


class NullGuestStarter(object):
    def start(self):
        pass


def create_guest_starter(hypervisor, executor):
    factories = [
        VirtualBoxBasedGuestStarterFactory(executor),
        XenServerBasedGuestStarterFactory(executor)
    ]

    for factory in factories:
        starter = factory.create_guest_starter(hypervisor)
        if starter:
            return starter


class VirtualBoxBasedGuestStarterFactory(object):
    def __init__(self, executor):
        self.executor = executor

    def create_guest_starter(self, url):
        match = re.match(r"""
        virtualbox-pfwd:
        (?P<ports_forwarded_to>[^:]+):
        (?P<vm_name>\w+)/
        (?P<snapshot_name>\w+)
        """, url, re.VERBOSE)

        if match:
            starter = VirtualBoxBasedGuestStarter(
                vm_name=match.group('vm_name'),
                snapshot_name=match.group('snapshot_name'),
                executor=self.executor,
                ports_forwarded_to=match.group('ports_forwarded_to'))
            return starter


class XenServerBasedGuestStarterFactory(object):
    def __init__(self, executor):
        self.executor = executor

    def create_guest_starter(self, url):
        match = re.match(r"""
        xenserver:
        (?P<username>[^@]+)@
        (?P<host>[^:]+):
        (?P<password>[^:]+):
        (?P<vm_name>[^/]+)/
        (?P<snapshot_name>\w+)
        """, url, re.VERBOSE)

        if match:
            return XenServerBasedGuestStarter(
                vm_name=match.group('vm_name'),
                snapshot_name=match.group('snapshot_name'),
                executor=OverSSHExecutor(
                    self.executor,
                    match.group('username'),
                    match.group('host'),
                    match.group('password')
                )
            )


class VirtualBoxBasedGuestStarter(vm_snapshot.VMSnapShotParty):
    def __init__(self, vm_name, snapshot_name, executor, ports_forwarded_to):
        super(VirtualBoxBasedGuestStarter, self).__init__(
            vm_name, snapshot_name)
        self.executor = executor
        self.ports_forwarded_to = ports_forwarded_to

    def start(self):
        guest_vm = guest.VirtualBoxHostedGuest(
            self.vm_name, self.executor)
        guest_vm.stop()
        guest_vm.restore(self.snapshot_name)
        guest_vm.start()
        return self.ports_forwarded_to


class XenServerBasedGuestStarter(object):
    def __init__(self, vm_name, snapshot_name, executor):
        self.vm_name = vm_name
        self.snapshot_name = snapshot_name
        self.executor = executor

    def start(self):
        guest_vm = guest.XenServerBasedHostedGuest(
            self.vm_name, self.executor)
        guest_vm.stop()
        guest_vm.restore(self.snapshot_name)
        guest_vm.resume()
        return guest_vm.get_ip()
