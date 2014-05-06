import unittest
import mock

import sys
from xenrt_loader import loader


class FakeXenRT(object):
    pass


class TestLoader(unittest.TestCase):
    def fake_xenrt_import(self):
        sys.modules['xenrt'] = FakeXenRT()

    @mock.patch('xenrt_loader.loader.read_file')
    def test_sys_path_modified(self, read_file):
        self.fake_xenrt_import()
        read_file.return_value = ''
        loader.load_xenrt('somepath')

        self.assertIn('somepath/exec', sys.path)
        self.assertIn('somepath/lib', sys.path)
