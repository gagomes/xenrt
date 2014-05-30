import unittest

from guest_launcher import executor
from guest_launcher import guest
from guest_launcher.tests.mocks import MockExecutor


class TestVirtualBoxHostedGuest(unittest.TestCase):
    def test_start_vm_runs_vboxmanage(self):
        mock_executor = MockExecutor()
        vb = guest.VirtualBoxHostedGuest("windows", executor=mock_executor)

        vb.start()

        self.assertEquals(
            ['vboxmanage startvm windows --type headless'.split()],
            mock_executor.executed_commands
        )

    def test_stop_runs_controlvm(self):
        mock_executor = MockExecutor()
        vb = guest.VirtualBoxHostedGuest("windows", executor=mock_executor)

        vb.stop()

        self.assertEquals(
            [
                'vboxmanage showvminfo windows --machinereadable'.split(),
                'vboxmanage controlvm windows poweroff'.split()
            ],
            mock_executor.executed_commands
        )

    def test_stop_does_nothing_if_vm_is_stopped(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('showvminfo').then_return(
            stdout='VMState="poweroff"')
        vb = guest.VirtualBoxHostedGuest("windows", executor=mock_executor)

        vb.stop()

        self.assertEquals(
            [
                'vboxmanage showvminfo windows --machinereadable'.split(),
            ],
            mock_executor.executed_commands
        )

    def test_snapshot_takes_snapshot(self):
        mock_executor = MockExecutor()
        vb = guest.VirtualBoxHostedGuest("windows", executor=mock_executor)

        vb.snap('test_snapshot')

        self.assertEquals(
            ['vboxmanage snapshot windows take test_snapshot --pause'.split()],
            mock_executor.executed_commands
        )

    def test_restore_reverts_from_snapshot(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('snapshot', 'list').then_return(
            stdout='SnapshotName="test_snapshot"')
        vb = guest.VirtualBoxHostedGuest("windows", executor=mock_executor)

        vb.restore('test_snapshot')

        self.assertEquals(
            [
                'vboxmanage snapshot windows list --machinereadable'.split(),
                'vboxmanage snapshot windows restore test_snapshot'.split()
            ],
            mock_executor.executed_commands
        )

    def test_restore_fails_if_snapshot_not_found(self):
        mock_executor = MockExecutor()
        vb = guest.VirtualBoxHostedGuest("windows", executor=mock_executor)

        with self.assertRaises(guest.SnapshotNotFoundException) as ctx:
            vb.restore('test_snapshot')

        self.assertIn('test_snapshot', ctx.exception.message)


class TestXenServerBasedHostedGuest(unittest.TestCase):
    def test_start_executes_xe_vm_start(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('vm-list').then_return(
            stdout='SOMEUUID')
        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        vm.start()

        self.assertEquals(
            [
                'xe vm-list name-label=vmname --minimal'.split(),
                'xe vm-start uuid=SOMEUUID'.split(),
            ],
            mock_executor.executed_commands
        )

    def test_stop_executes_vm_shutdown_forced(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('vm-list').then_return(
            stdout='SOMEUUID')
        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        vm.stop()

        self.assertEquals(
            [
                'xe vm-list name-label=vmname --minimal'.split(),
                'xe vm-shutdown uuid=SOMEUUID force=true'.split(),
            ],
            mock_executor.executed_commands
        )

    def test_restore(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('snapshot-list').then_return(
            stdout='SNAPUUID\n')
        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        vm.restore('snap')

        self.assertEquals(
            [
                'xe snapshot-list name-label=snap --minimal'.split(),
                'xe snapshot-revert snapshot-uuid=SNAPUUID'.split(),
            ],
            mock_executor.executed_commands
        )

    def test_snap(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('vm-list').then_return(
            stdout='SOMEUUID')
        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        vm.snap('snap')

        self.assertEquals(
            [
                'xe vm-list name-label=vmname --minimal'.split(),
                'xe vm-checkpoint new-name-label=snap vm=SOMEUUID'.split(),
            ],
            mock_executor.executed_commands
        )

    def test_newlines_stripped(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('vm-list').then_return(
            stdout='SOMEUUID\n')
        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        uuid = vm._get_vm_uuid()

        self.assertEquals('SOMEUUID', uuid)

    def test_resume(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('vm-list').then_return(
            stdout='SOMEUUID')
        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        vm.resume()

        self.assertEquals(
            [
                'xe vm-list name-label=vmname --minimal'.split(),
                'xe vm-resume vm=SOMEUUID'.split(),
            ],
            mock_executor.executed_commands
        )

    def test_get_ip_makes_the_righ_calls(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('vm-list').then_return(
            stdout='SOMEUUID')

        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        vm.get_ip()

        self.assertEquals(
            [
                'xe vm-list name-label=vmname --minimal'.split(),
                (
                    'xe vm-param-get '
                    'param-name=networks uuid=SOMEUUID --minimal'
                ).split(),
            ],
            mock_executor.executed_commands
        )

    def test_get_ip_returns_ip_address(self):
        mock_executor = MockExecutor()
        mock_executor.if_found('vm-list').then_return(
            stdout='SOMEUUID')
        mock_executor.if_found('param-name=networks').then_return(
            stdout='rubbish0/ip: 10.220.101.226rubbish')

        vm = guest.XenServerBasedHostedGuest("vmname", mock_executor)

        ipaddr = vm.get_ip()

        self.assertEquals(
            '10.220.101.226', ipaddr)
