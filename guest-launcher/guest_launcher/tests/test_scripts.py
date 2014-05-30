import unittest
import mock

import logging

from guest_launcher import scripts
from guest_launcher import guest_starter


class TestArgParsingForSnap(unittest.TestCase):
    def test_guest_spec_parsed(self):
        options = scripts.parse_args_for_snap(['somearg'])

        self.assertEquals('somearg', options.guest_spec)

    def test_parsing_quits_if_no_guest_spec(self):
        with self.assertRaises(SystemExit) as ctx:
            scripts.parse_args_for_snap([])

        self.assertTrue(0 != ctx.exception.code)


class TestInitLogging(unittest.TestCase):
    def test_logging_initialised(self):
        scripts.init_logging()

        self.assertTrue(
            logging.getLogger(__name__).isEnabledFor(logging.DEBUG))


class MockerMixIn(object):
    def setUp(self):
        self.patchers = []

    def start_patchers(self):
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()


def mocked(*names_to_mock):
    def mocker(original_function):
        def mocked_function(self, *args, **kwargs):
            for name_to_mock in names_to_mock:
                self.patchers.append(
                    mock.patch(name_to_mock))
            self.start_patchers()
            return original_function(self, *args, **kwargs)
        mocked_function.__name__ = original_function.__name__
        return mocked_function
    return mocker


def start_deps_mocked():
    return mocked(
        'guest_launcher.scripts.init_logging',
        'guest_launcher.scripts.create_executor',
        'guest_launcher.scripts.parse_args_for_snap',
        'guest_launcher.scripts.guest_starter.create_guest_starter',
    )


class FakeParams(object):
    def __init__(self):
        self.guest_spec = 'guest-spec'


class TestStart(MockerMixIn, unittest.TestCase):
    @start_deps_mocked()
    def test_logging_initialised(self):
        scripts.start()

        scripts.init_logging.assert_called_once_with()

    @start_deps_mocked()
    def test_args_parsed(self):
        scripts.start()

        scripts.parse_args_for_snap.assert_called_once_with(None)

    @start_deps_mocked()
    def test_guest_starter_created(self):
        scripts.create_executor.return_value = 'executor'
        scripts.parse_args_for_snap.return_value = FakeParams()

        scripts.start()

        scripts.guest_starter.create_guest_starter.assert_called_once_with(
            'guest-spec', 'executor')

    @start_deps_mocked()
    def test_start_called_on_guest_starter(self):
        starter = mock.Mock(spec=guest_starter.VirtualBoxBasedGuestStarter)
        scripts.guest_starter.create_guest_starter.return_value = starter

        scripts.start()

        starter.start.assert_called_once_with()

    @start_deps_mocked()
    def test_ip_address_printed_out(self):
        stdout_mock = mock.Mock()
        starter = mock.Mock(spec=guest_starter.VirtualBoxBasedGuestStarter)
        scripts.guest_starter.create_guest_starter.return_value = starter
        starter.start.return_value = 'ipaddress'

        scripts.start(stdout=stdout_mock)

        self.assertEquals(
            [
                mock.call('ipaddress'),
                mock.call('\n')
            ],
            stdout_mock.write.mock_calls
        )
