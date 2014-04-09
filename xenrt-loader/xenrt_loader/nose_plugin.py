from nose.plugins import Plugin

from xenrt_loader.loader import load_xenrt


class XenRTImporterNosePlugin(Plugin):
    name = 'xenrt-loader'

    def configure(self, options, conf):
        if options.xenrt_path is None:
            self.enabled = False
            return
        load_xenrt(options.xenrt_path)

    def help(self):
        return "Load XenRT from the specified location"

    def options(self, parser, env):
        parser.add_option(
            '--with-xenrt',
            dest='xenrt_path',
            default=None,
            help='Load XenRT from the given path')
