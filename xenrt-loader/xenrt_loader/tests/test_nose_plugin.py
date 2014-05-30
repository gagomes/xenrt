import unittest
import mock
import optparse

from xenrt_loader import nose_plugin


class TestNosePlugin(unittest.TestCase):
    def test_name(self):
        plugin_cls = nose_plugin.XenRTImporterNosePlugin

        self.assertEquals('xenrt-loader', plugin_cls.name)

    def test_options_adds_option(self):
        plugin = nose_plugin.XenRTImporterNosePlugin()
        parser = optparse.OptionParser()

        plugin.options(parser, {})

        option = parser.get_option('--with-xenrt')
        self.assertEquals(1, option.nargs)
        self.assertEquals('xenrt_path', option.dest)

    @mock.patch(
        'xenrt_loader.nose_plugin.load_xenrt')
    def test_configure_sets_global_factory(self, load_xenrt):
        plugin = nose_plugin.XenRTImporterNosePlugin()
        plugin.enabled = True
        options = mock.Mock()
        options.xenrt_path = 'something'

        plugin.configure(options, None)

        load_xenrt.assert_called_once_with('something')
