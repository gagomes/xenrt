from nose.plugins import Plugin

from guest_launcher.guest_starter import create_guest_starter
from guest_launcher.guest_starter import NullGuestStarter
from guest_launcher import scripts


guest_starter = NullGuestStarter()


class GuestLauncherNosePlugin(Plugin):
    name = 'guest-launcher'

    def configure(self, options, conf):
        if options.with_guest_launcher is None:
            return
        global guest_starter
        guest_starter = create_guest_starter(
            options.with_guest_launcher,
            scripts.create_executor())

    def help(self):
        return "Configure a guest to be used by the tests"

    def options(self, parser, env):
        parser.add_option(
            '--with-{name}'.format(name=self.name),
            help='guest specification for the tests')
