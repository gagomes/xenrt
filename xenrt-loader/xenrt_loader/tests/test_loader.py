import unittest

import sys
from xenrt_loader import loader


class TestLoader(unittest.TestCase):
    def test_sys_path_modified(self):
        loader.load_xenrt('somepath')

        self.assertIn('somepath/exec', sys.path)
        self.assertIn('somepath/lib', sys.path)
