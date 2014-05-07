from testing import XenRTUnitTestCase
from xenrt.stringutils import RandomStringGenerator


class testRandomStringGenerator(XenRTUnitTestCase):

    def setUp(self):
        self.__rsg = RandomStringGenerator()

    def testStringIsReturedFromGenerate(self):
        """Given a call to generate, then expect a string to be returned"""
        self.assertIs(type(self.__rsg.generate()), str)

    def testRandomStringDefaultLength(self):
        """Given generate creates as string, then check the length is equal
        to the generated string length"""
        self.assertEqual(self.__rsg.length, len(self.__rsg.generate()))

    def testMultipleCallsDoNotGenerateTheSameValue(self):
        """Given multiple calls to generate, when the output is searched
        for unique values, then expect none to be found"""
        data = [self.__rsg.generate() for _ in range(100)]
        uniqueData = set(data)
        self.assertEqual(len(data), len(uniqueData))
