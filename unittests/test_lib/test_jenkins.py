import unittest


class FailingTest(unittest.TestCase):
    def test_failing(self):
        self.assertTrue(False)
