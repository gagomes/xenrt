import logging
import re


log = logging.getLogger(__name__)


class SnapshotNotFoundException(Exception):
    pass


class VirtualBoxHostedGuest(object):
    def __init__(self, vm_name, executor):
        self.vm_name = vm_name
        self.executor = executor

    def _run_or_raise(self, args):
        result = self.executor.run(args)
        if result.returncode != 0:
            log.error('stderr: %s', result.stderr)
            log.error('stdout: %s', result.stdout)
            raise Exception()
        return result

    def start(self):
        log.info("Starting Guest")
        self._run_or_raise([
            'vboxmanage',
            'startvm',
            self.vm_name,
            '--type',
            'headless'])

    def _has_snapshot(self, snapshot_name):
        result = self._run_or_raise([
            'vboxmanage',
            'snapshot',
            self.vm_name,
            'list',
            '--machinereadable'])

        snap_name_entry = 'SnapshotName="{snapshot_name}"'.format(
            snapshot_name=snapshot_name)
        if snap_name_entry in result.stdout:
            return True

    def _is_stopped(self):
        result = self._run_or_raise([
            'vboxmanage',
            'showvminfo',
            self.vm_name,
            '--machinereadable'])

        if 'VMState="poweroff"' in result.stdout:
            return True

    def stop(self):
        if self._is_stopped():
            log.info("Guest already stopped")
            return
        log.info("Stopping Guest")
        self._run_or_raise([
            'vboxmanage',
            'controlvm',
            self.vm_name,
            'poweroff'])

    def snap(self, snapshot_name):
        log.info("Snapshotting Guest")
        self._run_or_raise([
            'vboxmanage',
            'snapshot',
            self.vm_name,
            'take',
            snapshot_name,
            '--pause'])

    def restore(self, snapshot_name):
        if not self._has_snapshot(snapshot_name):
            raise SnapshotNotFoundException(snapshot_name)
        log.info("Restoring Guest")
        self._run_or_raise([
            'vboxmanage',
            'snapshot',
            self.vm_name,
            'restore',
            snapshot_name])


class XenServerBasedHostedGuest(object):
    def __init__(self, vm_name, executor):
        self.executor = executor
        self.vm_name = vm_name

    def _run_or_raise(self, args):
        result = self.executor.run(args)
        if result.returncode != 0:
            raise Exception(result.as_logstring())
        return result

    def _get_vm_uuid(self):
        result = self._run_or_raise(
            [
                'xe',
                'vm-list',
                'name-label={vm_name}'.format(vm_name=self.vm_name),
                '--minimal'
            ]
        )
        return result.stdout.strip()

    def start(self):
        vm_uuid = self._get_vm_uuid()
        self._run_or_raise(
            [
                'xe',
                'vm-start',
                'uuid={vm_uuid}'.format(vm_uuid=vm_uuid),
            ]
        )

    def resume(self):
        vm_uuid = self._get_vm_uuid()
        self._run_or_raise(
            [
                'xe',
                'vm-resume',
                'vm={vm_uuid}'.format(vm_uuid=vm_uuid),
            ]
        )

    def stop(self):
        vm_uuid = self._get_vm_uuid()
        self._run_or_raise(
            [
                'xe',
                'vm-shutdown',
                'uuid={vm_uuid}'.format(vm_uuid=vm_uuid),
                'force=true'
            ]
        )

    def restore(self, snapshot_name):
        result = self._run_or_raise(
            [
                'xe',
                'snapshot-list',
                'name-label={snapshot_name}'.format(
                    snapshot_name=snapshot_name),
                '--minimal'
            ]
        )
        snapshot_uuid = result.stdout.strip()
        self._run_or_raise(
            [
                'xe',
                'snapshot-revert',
                'snapshot-uuid={snapshot_uuid}'.format(
                    snapshot_uuid=snapshot_uuid),
            ]
        )

    def snap(self, snapshot_name):
        vm_uuid = self._get_vm_uuid()
        self._run_or_raise(
            [
                'xe',
                'vm-checkpoint',
                'new-name-label={snapshot_name}'.format(
                    snapshot_name=snapshot_name),
                'vm={vm_uuid}'.format(
                    vm_uuid=vm_uuid)
            ]
        )

    def get_ip(self):
        vm_uuid = self._get_vm_uuid()
        result = self._run_or_raise(
            [
                'xe',
                'vm-param-get',
                'param-name=networks',
                'uuid={vm_uuid}'.format(
                    vm_uuid=vm_uuid),
                '--minimal'
            ]
        )

        networks = result.stdout
        match = re.match(r"""
        .*
        0/ip:\ (?P<ipaddress>[0-9.]+)
        [^0-9.]
        .*
        """, networks, re.VERBOSE)

        if match:
            return match.group('ipaddress')
