import re


class VMSnapShotParty(object):
    def __init__(self, vm_name, snapshot_name):
        self.vm_name = vm_name
        self.snapshot_name = snapshot_name


def url_to_vm_snapshot_based(url, klass):
    match = re.match(r"""
        virtualbox:
        (?P<vm_name>\w+)/
        (?P<snapshot_name>\w+)
        """, url, re.VERBOSE)
    if match:
        return klass(
            vm_name=match.group('vm_name'),
            snapshot_name=match.group('snapshot_name'))
