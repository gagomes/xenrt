import unittest

from guest_launcher import executor
from guest_launcher.tests import mocks


class TestSSHWrapper(unittest.TestCase):
    def test_wrapping(self):
        mock_executor = mocks.MockExecutor()
        decorator = executor.OverSSHExecutor(
            mock_executor, 'username', 'host', 'password')

        decorator.run(['ls'])

        self.assertEquals(
            [
                (
                    'sshpass -ppassword'
                    ' ssh -q -o StrictHostKeyChecking=no'
                    ' -o UserKnownHostsFile=/dev/null'
                    ' username@host ls'
                ).split()
            ],
            mock_executor.executed_commands)

    def test_result_returned(self):
        mock_executor = mocks.MockExecutor()
        mock_executor.if_found('ls').then_return(stdout='hello')
        decorator = executor.OverSSHExecutor(
            mock_executor, 'username', 'host', 'password')

        result = decorator.run(['ls'])

        self.assertEquals(
            'hello', result.stdout)
