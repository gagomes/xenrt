import unittest
import mock
import optparse

from guest_launcher import nose_plugin
from guest_launcher import guest_starter


class TestNosePlugin(unittest.TestCase):
    def setUp(self):
        self.saved_starter = nose_plugin.guest_starter

    def test_name(self):
        plugin_cls = nose_plugin.GuestLauncherNosePlugin

        self.assertEquals('guest-launcher', plugin_cls.name)

    def test_options_adds_option(self):
        plugin = nose_plugin.GuestLauncherNosePlugin()
        parser = optparse.OptionParser()

        plugin.options(parser, {})

        option = parser.get_option('--with-guest-launcher')
        self.assertEquals(1, option.nargs)
        self.assertEquals('with_guest_launcher', option.dest)

    @mock.patch(
        'guest_launcher.nose_plugin.create_guest_starter')
    def test_configure_sets_global_factory(self, create_guest_starter):
        plugin = nose_plugin.GuestLauncherNosePlugin()
        plugin.enabled = True
        options = mock.Mock()
        options.with_guest_launcher = 'something'
        create_guest_starter.return_value = 'guest_starter'

        plugin.configure(options, None)

        self.assertEquals('guest_starter', nose_plugin.guest_starter)

    def test_default_guest_starter(self):
        self.assertEquals(
            guest_starter.NullGuestStarter,
            type(nose_plugin.guest_starter)
        )

    def tearDown(self):
        nose_plugin.guest_starter = self.saved_starter
