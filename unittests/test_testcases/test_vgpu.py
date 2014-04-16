"""
Sample code to demonstrate the proof of concept of unit testing
of test case code
"""

from mock import patch, Mock, PropertyMock
from testing import XenRTTestCaseUnitTestCase
from testcases.xenserver.tc.vgpu import VGPUOS, VGPUConfig
from testcases.xenserver.tc.vgpu import _VGPUScalabilityTest
import xenrt


class TestScalabilityTest(XenRTTestCaseUnitTestCase):

    def __setupTasks(self, bootstorm):
        self.bootstorm = bootstorm
        self.test = _VGPUScalabilityTest([VGPUOS.Win7x64], VGPUConfig.K100,
                                         self.bootstorm)
        self.test.host = Mock(return_value=self._createHost())
        self.test._runWorkload = Mock(return_value="mock data")
        self.test._measureMetric = Mock()
        self.test.rebootAllVMs = Mock()

    @patch("time.time")
    @patch("xenrt.sleep")
    def test_bootstorm_looping_mechanism_executes(self, sleep, time):
        """
        Given a bootstorming vgpu test case, when the long-term loop is
        entered, then check reboot is successfully called and the loop exits
        without problem and metrics are measured twice per loop
        """
        self.__setupTasks(True)
        time.side_effect = [1, 1, 99999]

        self.test.run(None)

        self.test.rebootAllVMs.assert_called_once_with()
        self.assertEqual(2, self.test._measureMetric.call_count)

    @patch("time.time")
    @patch("xenrt.sleep")
    def test_serial_reboot(self, sleep, time):
        """
        Given a vgpu scalability tests, when a serial reboot is requested,
        then expect the run loop to be exited without problem and reboot is
        called once
        """
        self.__setupTasks(False)
        time.side_effect = [1, 1, 999999]
        guests = [(Mock(spec=xenrt.lib.xenserver.Guest), VGPUConfig.K100)
                  for x in range(5)]
        type(self.test)._guestsAndTypes = PropertyMock(return_value=guests)

        self.test.run(None)

        [m.reboot.assert_called_once_with() for m, t  in  guests]
        self.assertEqual(0, self.test.rebootAllVMs.call_count)
        self.assertEqual(2, self.test._measureMetric.call_count)
