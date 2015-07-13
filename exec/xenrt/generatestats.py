import urllib, urllib2, json, math, re
from datetime import datetime, timedelta
import xenrt
from xenrt.lazylog import step, comment, log, warning

class LabCostPerTechArea():

    def __init__(self, suiteId, nbrOfSuiteRunsToCheck=5, arglist=None):
        self.suiteId = suiteId
        self.nbrOfSuiteRunsToCheck = nbrOfSuiteRunsToCheck

    def generate(self):
        step("Get latest suite run history")
        u = urllib.urlopen("%s/suitehistoryjson/%s" % (xenrt.TEC().lookup("TESTRUN_URL"), self.suiteId)).read().strip()
        suiteRunData = json.loads(u if u.startswith("{") else "{}")
        suiteRunIds = [int(srid) for srid in suiteRunData.keys()]
        suiteRunIds.sort(reverse=True)

        step("Add all dummy variables which might be required by any suite.")
        xenrt.TEC().config.setVariable("JIRA_TICKET_TAG", "Test")
        xenrt.TEC().config.setVariable("THIS_HOTFIX", "Test")
        xenrt.TEC().config.setVariable("CLOUDINPUTDIR", "Test")
        xenrt.TEC().config.setVariable("EXTERNAL_LICENSE_SERVER", "Test")
        xenrt.TEC().config.setVariable("PRODUCT_VERSION", "Test")

        step("Get testcase and sequence details from suite")
        suite = xenrt.suite.Suite(self.suiteId)
        suiteData = {seq.seq: {"testcases":[tc.split("_")[0] if re.match("^TC-\d+$", tc.split("_")[0]) else None for tc in seq.listTCsInSequence(quiet=True)]} for seq in suite.sequences}

        step("Get job details")
        for srid in suiteRunIds[:min(self.nbrOfSuiteRunsToCheck,len(suiteRunIds))]:
            log("Fetching job details from suite run %d" %srid)
            jobData= xenrt.APIFactory().get_jobs(status="done", suiterun=srid, params=True, limit=len(suiteData))
            for job in jobData:
                try:
                    seq = jobData[job]['params']['DEPS']
                    startTime = datetime.strptime(jobData[job]['params']['STARTED'][:-4],"%a %b %d %H:%M:%S %Y")
                    finishTime = datetime.strptime(jobData[job]['params']['FINISHED'][:-4],"%a %b %d %H:%M:%S %Y")
                    executionTime = finishTime-startTime
                    nbrOfMachines = int(jobData[job]['params']['MACHINES_REQUIRED'])
                    if seq in suiteData:
                        if not "jobCount" in suiteData[seq]:
                            suiteData[seq]["runtime"]= executionTime * nbrOfMachines
                            suiteData[seq]["jobCount"]= 1
                        else:
                            suiteData[seq]["runtime"]= ( executionTime * nbrOfMachines + suiteData[seq]["runtime"]*suiteData[seq]["jobCount"] ) / (suiteData[seq]["jobCount"]+1)
                            suiteData[seq]["jobCount"] += 1
                except Exception,e: 
                    log("WARNING: Job %s has exception: %s" % (job, e))

        step("Processing Data: seq as primary key -> testcase as primary key")
        tcData={}
        TimeMissingTAInfo = timedelta(0, 0, 0)
        tcMissingHistory = []
        for seq in suiteData:
            tcCountInSeq = len(suiteData[seq]['testcases'])
            if not "runtime" in suiteData[seq]:
                tcMissingHistory.extend(suiteData[seq]['testcases'])
            elif not tcCountInSeq:
                TimeMissingTAInfo += suiteData[seq]['runtime']
            else:
                for tc in suiteData[seq]['testcases']:
                    if tc in tcData and 'runtime' in tcData[tc]:
                        #possibly testcase has multiple runs, then we add time
                        tcData[tc]['runtime'] += suiteData[seq]['runtime']/tcCountInSeq
                    elif tc:
                        tcData.update( {tc:{ 'runtime':( suiteData[seq]['runtime']/tcCountInSeq) }})

        step("Fetching TechArea for each TA from Jira.")
        tcIds = tcData.keys()
        totalCount = len(tcIds)
        if totalCount:
            count=0
            maxCountAllowed = 25
            j = xenrt.jiralink.getJiraLink()
            while count <= totalCount:
                log("\tfetching part %d/%d"% (math.ceil(count/maxCountAllowed+1), math.ceil(totalCount/maxCountAllowed+1)))
                tcIdsSub= tcIds[count:min(count+maxCountAllowed, totalCount)]
                count +=maxCountAllowed
                query='Key in (%s)' % ",".join(tcIdsSub)
                result = j.jira.search_issues(query, maxResults=maxCountAllowed)
                [tcData[issue.key].update({'techarea':([comp.name for comp in issue.fields.components][0])}) if issue.fields.components else None for issue in result]

        step("Processing Data. testcase as primary key -> techArea as primary key")
        techAreaData = {'Unknown' : TimeMissingTAInfo.total_seconds()/3600}
        for tc in tcData:
            if not 'techarea' in tcData[tc]:
                techAreaData['Unknown'] += tcData[tc]['runtime'].total_seconds()/3600
            elif not tcData[tc]['techarea'] in techAreaData:
                techAreaData[tcData[tc]['techarea']]= tcData[tc]['runtime'].total_seconds()/3600
            else:
                techAreaData[tcData[tc]['techarea']] += tcData[tc]['runtime'].total_seconds()/3600

        log("Cost per TA (machineHours): %s" % techAreaData)
        log("TCs having no run history : %s" % tcMissingHistory)
        return (techAreaData, tcMissingHistory)
