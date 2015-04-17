#
# XenRT: Test harness for Xen and the XenServer product family
#
# Generic solution for performance test cases functionality.

import xenrt, json
from datetime import datetime

class PerformanceUtility(object):
    """Class which holds some performance testcase functionality."""
    __performanceRuns = 0

    def __init__(self, runs=1, scenarioData={}, normalized=False):
        """Inits PU using..

        Args:
            runs: Number of runs to perform the test on the function.
            scenarioData: Dictionary of any relavent data which you wish to 
                store in the log file, along with the timing results.
            normalized: If you wish the results to be normalized. The slowest 
                and fastest run will be ignored if True. (Will default to 
                minimum of 3 runs if normalized is True)
        """
        self.__runs = runs
        self.__scenarioData = scenarioData
        self.__normalized = normalized
        self.__timingDataResults = {}
        self.__results = []

        if self.__runs < 1:
            self.__runs = 1

        if self.__normalized and self.__runs < 3:
            self.__runs = 3

    def executePerformanceTest(self, functionRun, functionCleanup=None):
        """Run a given function (and cleanup) a given number of times, 
            times it, and records the results from the test.

        Args:
            functionRun: Pointer to function that will be timed when running.
            functionCleanup: Point to function that will cleanup after 
                every run. (Optional)
        """
        self.__performanceRuns += 1
        xenrt.TEC().logverbose("Amount of runs: %s" % self.__runs)

        self.__executeRuns(functionRun, functionCleanup)
        self.__calculateRunTime()
        self.__dumpResults()

    def __executeRuns(self, functionRun, functionCleanup):
        """Run a given function (and cleanup) a given number of times."""
        for i in range(self.__runs):
            startTime = datetime.now()

            functionRun()

            endTime = datetime.now()

            # Cleanup after run.
            # Don't cleanup if no cleanup function, or if the last iteration.
            if functionCleanup != None:
                if i != range(self.__runs)[-1]:
                    functionCleanup()

            xenrt.TEC().logverbose("Start: %s" % startTime)
            xenrt.TEC().logverbose("End: %s" % endTime)

            runTime = endTime - startTime
            runResult = self.__totalSeconds(runTime)
            xenrt.TEC().logverbose("Time taken for run #%i: %s seconds." %
                                    (i+1, runResult))
            self.__results.append(runResult)

    def __calculateRunTime(self):
        """Calculate the average time taken for the group of run(s)."""
        totalTime = sum(self.__results)
        totalRuns = len(self.__results)

        # Want to remove the results from totals, but not the record of them.
        if self.__normalized:
            assert(len(self.__results) >= 3)
            totalTime -= max(self.__results)
            totalTime -= min(self.__results)
            totalRuns -= 2

        averageRunTime =  totalTime / totalRuns
        xenrt.TEC().logverbose("Data collected from %i runs" % 
                                len(self.__results))
        xenrt.TEC().logverbose("Average time taken for a run: %s seconds." % 
                                averageRunTime)

        self.__timingDataResults["run-times-in-seconds"] = self.__results
        self.__timingDataResults["average-run-time-in-seconds"] = averageRunTime
        self.__timingDataResults["result-normalized"] = self.__normalized

    def __dumpResults(self):
        """Write the results of the run to JSON file"""
        exportData = {}
        exportData["TimingData"] = self.__timingDataResults
        exportData["ScenarioData"] = self.__scenarioData

        logdir = xenrt.TEC().getLogdir()

        filename = "%s/timed-results-run-%s" % (logdir, self.__performanceRuns)

        with open(filename, "w") as f:
            f.write(json.dumps(exportData))

    def __totalSeconds(self, td):
        """Util function, td.total_seconds() only in python 2.7"""
        return (td.microseconds + 
                (td.seconds + td.days * 24 * 3600) * 10**6) / 10**float(6)
