from mock import patch, Mock, PropertyMock
import xenrt
from testing import XenRTUnitTestCase

class TestFindingSeqFile(XenRTUnitTestCase):
    BASE = "base"

    def test_found_path_is_correctly_augmented(self):
        data = [ ("bob.my.seq", "base/seqs/bob.my.seq"),
                ("home/bob", "base/seqs/home/bob"),
                ("/home/bob/my.seq", "/home/bob/my.seq"),
                ("../junk", "base/seqs/../junk"),
                ("", "base/seqs/") ]

        self.run_for_many(data, self.__test_expected_paths_found)
    
    @patch("xenrt.TEC")
    @patch("os.path.exists")
    def test_expected_paths_not_found_raises_exception(self, ospath, tec):
        tec.return_value.lookup.return_value = "junk"
        ospath.return_value = False
        self.assertRaises(xenrt.XRTError, xenrt.sequence.findSeqFile, "some/path")

    def test_duck_typing_issues_raise_errors(self):
        check = lambda x: self.assertRaises(AttributeError, xenrt.sequence.findSeqFile, x)
        data = [ None, 1, [1,2,3]]
        self.run_for_many(data, check)
        
    @patch("xenrt.TEC")
    @patch("os.path.exists")
    def __test_expected_paths_found(self, data, ospath, tec):
        path, expected  = data 
        tec.return_value.lookup.return_value = self.BASE
        ospath.return_value = True
        result = xenrt.sequence.findSeqFile(path)
        self.assertEqual(expected, result)

class NonFragmentDouble(object):
    def __len__(self): return 1

class TestFragmentStepAdding(XenRTUnitTestCase):
        
    @patch("xenrt.TEC")
    def test_add_step(self, tec):
        data = [ [("a", "b")], 
                 [("a", "b"), ("a", "b", "c"), xenrt.sequence.SingleTestCase("a", "b")],
                 [("a", "b"), ("a", "b", "c")]]
        self.expectedType = xenrt.sequence.SingleTestCase
        self.run_for_many(data, self.__test_add_step)

    def test_add_arg_type_switch_raises(self):
        fd = NonFragmentDouble()
        data = [("a"), fd]
        check = lambda x: self.assertRaises(xenrt.XRTError, xenrt.sequence.Fragment(None, []).addStep, x)
        self.run_for_many(data, check)


    @patch("xenrt.TEC")
    def test_add_step_invalid_arg(self, tec):
        self.assertRaises(ValueError, xenrt.sequence.Fragment(None, []).addStep, ("a","b","c","d"))
    
    @patch("xenrt.TEC")
    def __test_add_step(self, data, tec):
        f = xenrt.sequence.Fragment(None, [])
        [f.addStep(singleData) for singleData in data]
        self.assertEqual(len(data), len(f.steps))
        [self.assertIsInstance(x, xenrt.sequence.Fragment) for x in f.steps]

class TestFragmentRunning(XenRTUnitTestCase):

    def setUp(self):
        self.f = xenrt.sequence.Fragment(None, [])
        self.s = Mock()
        self.s.acquire = Mock()
        self.s.release = Mock()
        self.f.setSemaphore(self.s)
    
    def test_semaphore_setup_and_released(self):
        self.f.runThis = Mock(return_value=1)
        self.f.run()
        self.__check_calls()

    def test_semaphore_setup_and_released_exception(self):
        self.f.runThis = Mock(side_effect=Exception())
        self.assertRaises(Exception, self.f.run)
        self.__check_calls()

    def __check_calls(self):
        self.assertEqual(1, self.f.runThis.call_count)
        self.assertEqual(1, self.s.acquire.call_count)
        self.assertEqual(1, self.s.release.call_count)

class StepDouble(object):
    def __len__(self): return 1
    def listTCs(self): return ["TC", "CH"]
    def runThis(self): pass

class TestFragmentTCList(XenRTUnitTestCase):
    def setUp(self):
        self.f = xenrt.sequence.Fragment(None, [])
   
    def test_list_with_tcsku_jira_present_valid_data(self):
        testAndExpected = [("bob", ["fake_bob"]), (None, ["fake"])]
        self.f.jiratc = "fake"
        self.run_for_many(testAndExpected, self.__test_list_with_tcsku_jira_present)

    def test_list_with_tcsku_jira_present_invalid_data(self):
        badTypes = [1, ["junk", None], {"junk": None}]
        self.f.jiratc = "fake"
        self.run_for_many(badTypes, self.__test_list_with_tcsku_raises_on_type)

    def __test_list_with_tcsku_raises_on_type(self, value):
       self.f.tcsku = value
       self.assertRaises(TypeError, self.f.listTCs)
        
    def __test_list_with_tcsku_jira_present(self, dataPair):
       value, expected = dataPair
       self.f.tcsku = value
       self.assertEqual(self.f.listTCs(), expected)

    def test_steps(self):
       self.f.jiratc = None
       self.f.tcsku = None
       [self.f.addStep(StepDouble()) for n in range(3)]
       self.assertEqual(self.f.listTCs(), ['TC', 'CH', 'TC', 'CH', 'TC', 'CH'])

"""
Capture behaviour of the handle subnode method before refactoring
"""
class TestHandlingSubNodes(XenRTUnitTestCase):
    def setUp(self):
        self.f = xenrt.sequence.Fragment(None, [])
        self.f.addStep = Mock()
 
    @patch("xenrt.sequence.Serial")
    def test_serialStepIsAdded(self, ms):
        ms.handleXMLNode = Mock()
        nd = Mock()
        type(nd).localName = PropertyMock(return_value = "serial")
        self.f.handleSubNode(None, nd)
        
        self.f.addStep.assert_called_with(ms.return_value)
        self.assertEqual(1, self.f.addStep.call_count)

        

