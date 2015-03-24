from xenrt.txt import TXTErrorParser, TxtLogObfuscator
from testing import XenRTUnitTestCase
from mock import Mock, patch


class TestTxtLogObfuscator(XenRTUnitTestCase):

    def testTimeIsFuzzed(self):
        data = ["Jul 18 11:43:25 localhost xentpm[8593]: The TPM is not pwned"]
        fuzz = TxtLogObfuscator(data)
        self.assertEqual(["""Jul 18 XX:XX:XX localhost xentpm[8593]: The """
                          """TPM is not pwned"""], fuzz.fuzzTimes())

    def testDateIsFuzzed(self):
        data = ["Jul 18 11:43:25 localhost xentpm[8593]: The TPM is not pwned"]
        fuzz = TxtLogObfuscator(data)
        self.assertEqual(["""XXX XX 11:43:25 localhost xentpm[8593]: The """
                          """TPM is not pwned"""], fuzz.fuzzDates())

    def testThreadIsFuzzed(self):
        data = ["Jul 18 11:43:25 localhost xentpm[8593]: The TPM is not pwned"]
        fuzz = TxtLogObfuscator(data)
        self.assertEqual(["""Jul 18 11:43:25 localhost xentpm[XXXX]: The """
                          """TPM is not pwned"""], fuzz.fuzzThreadMarker())

    def testAllDataIsFuzzed(self):
        data = ["Jul 18 11:43:25 localhost xentpm[8593]: The TPM is not pwned"]
        fuzz = TxtLogObfuscator(data)
        self.assertEqual(["""XXX XX XX:XX:XX localhost xentpm[XXXX]: The """
                          """TPM is not pwned"""], fuzz.fuzz())

    def testSingleDigitDateIsFuzzed(self):
        data = ["Aug 2 11:43:25 localhost xentpm[8593]: The TPM is not pwned"]
        fuzz = TxtLogObfuscator(data)
        self.assertEqual(["""XXX XX 11:43:25 localhost xentpm[8593]: The """
                          """TPM is not pwned"""], fuzz.fuzzDates())


class TestTxtErrorParser(XenRTUnitTestCase):
    __HIT1 = "12:45: xentpm: owl icecream is my favourite\n"
    __HIT2 = "12:48: [TCSD TDDL]: I like scrambled snake\n"
    __NOHIT1 = "12:46: mouse: no gruffalo crumble is better\n"
    __NOHIT2 = "12:48: [gruffalo]: No its all about mouse sandwiches\n"
    __3ERR = "xentpm error help arggghhhhh expired, it's all broken - failed"
    __2ERR1 = "xentpm error help arggghhhhh, it's all broken - failed"
    __2ERR2 = "xentpm kaboom, fizz, clunk, clunk... I've failed - \
               probably not an ERROR though"
    __1ERR = "TCSD TDDL epicly failed"

    def testHitLinesAreFiltered(self):
        inputData = [self.__HIT1, self.__NOHIT1, self.__HIT2, self.__NOHIT2]
        parser = TXTErrorParser(inputData)
        result = parser.locateAllTpmData()
        [self.assertTrue(hit in result, "Couldn't find %s" % hit)
         for hit in [self.__HIT1, self.__HIT2]]

    def testWeightingPicksSingleHighestWeightedError(self):
        inputData = [self.__3ERR, self.__2ERR1, self.__1ERR]
        parser = TXTErrorParser(inputData)
        result = parser.locateKeyErrors()
        self.assertEqual([self.__3ERR], result)

    def testWeightingPicksTwoHighestWeightedError(self):
        inputData = [self.__HIT1, self.__2ERR2, self.__2ERR1,
                     self.__1ERR, self.__NOHIT1]
        parser = TXTErrorParser(inputData)
        result = parser.locateKeyErrors()
        self.assertEqual(sorted([self.__2ERR1, self.__2ERR2]), sorted(result))

    def testWeightingReturnsEmptyList(self):
        inputData = [self.__NOHIT1, self.__NOHIT2]
        parser = TXTErrorParser(inputData)
        self.assertEqual([], parser.locateKeyErrors())

    def testWeightingReturnsAnEmptyArrayWithAnEmptyLogFile(self):
        parser = TXTErrorParser([])
        self.assertEqual([], parser.locateKeyErrors())

    def testFilteringForHitLinesReturnsAnEmptyArrayForAnEmptyLog(self):
        parser = TXTErrorParser([])
        self.assertEqual([], parser.locateAllTpmData())

    @patch("xenrt.TEC")
    def testHostFileCtorOverloadMechanismCreatesInstance(self, mockTec):
        mockHost = Mock()
        mockHost.execcmd = Mock(side_effect=[0, self.__1ERR, 0, self.__2ERR1])
        parser = TXTErrorParser.fromHostFile(mockHost, "/some/file/name")
        self.assertEqual(sorted([self.__1ERR, self.__2ERR1]),
                         sorted(parser.locateAllTpmData()))
