import unittest
import pkg_resources
from guest_launcher import scripts
from guest_launcher import nose_plugin
from nose import tools


def assert_console_script(script_name, entry_point):
    """
    Make sure that entry_point is installed as a script script_name
    """
    assert_entry_point(script_name, entry_point, 'console_scripts')


def assert_entry_point(name, expected_entry_point, group):
    for ep in pkg_resources.iter_entry_points(group=group):
        if name == ep.name:
            break
    else:
        raise AssertionError(
            '{name} not found as a {group} entry point'.format(
                name=name, group=group))

    actual_entry_point = ep.load()
    tools.assert_equal(expected_entry_point, actual_entry_point)


class TestEntryPointsInstalled(unittest.TestCase):
    def test_gl_snap_installed(self):
        assert_console_script('gl-snap', scripts.snap)

    def test_guest_launcher_nose_plugin_installed(self):
        assert_entry_point(
            'guest-launcher',
            nose_plugin.GuestLauncherNosePlugin,
            'nose.plugins')

    def test_gl_start_installed(self):
        assert_console_script('gl-start', scripts.start)
