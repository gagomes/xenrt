#
# XenRT: Test harness for Xen and the XenServer product family
#
# Generic solution for performance test cases functionality.

import xenrt, json
from datetime import datetime

class PerformanceBase(xenrt.TestCase):
    """Decorator for TestCase which adds performance testing functionality."""
    def __init__(self, tc, runs=1, scenarioData={}, normalized=False):
        self._tc = tc
        self._runs = runs
        self._scenarioData = scenarioData
        self.normalized = normalized

        if self._runs < 1:
            self._runs = 1

        if self.normalized and self._runs < 3:
            self._runs = 3

    def timedRuns(self, fnP, fnC, *args, **kwargs):
        """Takes a function you want to run and time it."""
        self.timingDataResults = {}

        xenrt.TEC().logverbose("Amount of runs: %s" % self._runs)

        self.results = []

        self.executeRuns(fnP, fnC, *args, **kwargs)
        self.calculateRunTime()
        self.dumpResults()

    def executeRuns(self, fnP, fnC, *args, **kwargs):
        """Single run of the function you are performing."""
        for i in range(self._runs): 
            startTime = datetime.now()

            fnP(*args, **kwargs)

            endTime = datetime.now()
            # Clean up after run.
            fnC()
            xenrt.TEC().logverbose("Start: %s" % startTime)
            xenrt.TEC().logverbose("End: %s" % endTime)

            runTime = endTime - startTime
            runResult = self.totalSeconds(runTime)
            xenrt.TEC().logverbose("Time taken for run #%i: %s seconds." % (i+1, runResult))
            self.results.append(runResult)

    def calculateRunTime(self):
        """Calculates the average time taken for a single run"""
        # After X runs, the average run time is ...
        totalTime = sum(self.results)
        totalRuns = len(self.results)

        # Want to remove the results from totals, but not the record of them.
        if self.normalized:
            assert(len(self.results) >= 3)
            totalTime -= max(self.results)
            totalTime -= min(self.results)
            totalRuns -= 2

        averageRunTime =  totalTime / totalRuns
        xenrt.TEC().logverbose("Data collected from %i runs" % len(self.results))
        xenrt.TEC().logverbose("Average time taken for a run: %s seconds." % averageRunTime)

        self.timingDataResults["run-times-in-seconds"] = self.results
        self.timingDataResults["average-run-time-in-seconds"] = averageRunTime
        self.timingDataResults["result-normalized"] = self.normalized

    def dumpResults(self):
        """Writes the results of the run to JSON file"""
        exportData = {}
        exportData["TimingData"] = self.timingDataResults
        exportData["ScenarioData"] = self._scenarioData

        f = open("%s/timed-results.json" % (xenrt.TEC().getLogdir()), "w")
        f.write(json.dumps(exportData))
        f.close()

    def totalSeconds(self, timedelta):
        """Util function, timedelta.total_seconds() only in python 2.7"""
        return (timedelta.microseconds + (timedelta.seconds + timedelta.days * 24 * 3600) * 10**6) / 10**float(6)
