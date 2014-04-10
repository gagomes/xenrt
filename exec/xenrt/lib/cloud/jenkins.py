import xenrt, xenrt.lib.xenserver
import time, datetime
from datetime import datetime
import jenkinsapi
from jenkinsapi.jenkins import Jenkins
from abc import ABCMeta, abstractmethod
import os,subprocess,sys
from os import listdir

class BuildState: NotRunning, Running = range(2)

__all__ = ["JenkinsBuild","JenkinsObserver","InstallMarvin"]


#USE

#observer = JenkinsObserver()
#jenkinsBuild = JenkinsBuild() 
#jenkinsBuild.findBuild(sha1)
#jenkinsBuild.attachObserver(observer)
#observer.waitToFinish()
#jenkinsBuild.getBuildArtifacts()


class Build(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def attachObserver(self,buildObserver):
        pass
    
    def detachObserver(self):
        pass

    #def Notify()

    @abstractmethod
    def buildExists(self,sha1):
        pass

class BuildCommand(object):
    __metaclass__ = ABCMeta   
    _BuildJob = None

    def __init__(self,buildJob):

        self._BuildJob = buildJob

    @abstractmethod
    def invokeBuild(self,buildParams):
        pass

    @abstractmethod
    def getAllBuilds(self):
        pass
    
    @abstractmethod
    def buildStatus(self):
        pass
  
    @abstractmethod
    def getBuild(self,buildNum):
        pass

    @abstractmethod
    def getBuildArtifacts(self,build):
        pass

class JenkinsCommand(BuildCommand):

    def invokeBuild(self,buildParams):

        try:
            build = self._BuildJob.invoke(buildParams)
        except Exception, e:
            raise
 
        #Returns the jenkin's build obj to get the artifiacts
        return build

    def getAllBuilds(self):
      
        revDict = {}
        try:
            revDict = self._BuildJob.get_revision_dict()
        except Exception, e:
            raise
   
        #Returns the revision dict eg. {sha1: [1,2,3,4,5]}
        return revDict 

    def buildStatus(self,build):

        try:
            return build.get_status()
        except Exception, e:
            raise

    def buildRunning(self,build):

        try:
            return build.is_running()
        except Exception, e:
            raise

    def getBuild(self,buildNum):

        try:
            return self._BuildJob.get_build(int(buildNum))
        except Exception, e:
            raise

    def getBuildArtifacts(self,build):

        try:
            return build.get_artifact_dict()
        except Exception, e:
            raise

    def getJenkinsStatus(self):

        try:
            return self._BuildJob.is_running()
        except Exception, e:
            raise

class JenkinsBuild(Build):
    
    __JenkinsBuildState = BuildState.NotRunning
    __JenkinsURL = "http://cs-jenkins.xenrt.xs.citrite.net:8080"
    __Job = 'Cloudstack'
    __buildObj = None
    __buildName = 'Marvin'

    def __init__(self,buildURL = None):

        if buildURL:
            self.__JenkinsURL = buildURL       

        j = Jenkins(self.__JenkinsURL)
        if self.__Job not in j.keys():
            raise xenrt.XRTError('No Jenkins job found with id %s' % self.__Job)
   
        self.__JenkinsCommand = JenkinsCommand(j[self.__Job])

    def attachObserver(self,buildObserver):

        buildObserver.setBuildParams(self)
        buildObserver.startObserving()

    def state(self):

        if self.__JenkinsCommand.getJenkinsStatus() == False : 
            return BuildState.NotRunning
        else:
            return BuildState.Running
        
    def buildExists(self,sha1):

        buildDict = {}
        buildNums = []
        buildDict = self.__JenkinsCommand.getAllBuilds()

        if sha1 in buildDict.keys():
            # Take the latest build as single sha1 can have multiple builds
           
            buildNums = buildDict[sha1]

        return buildNums 
                 
    def findBuild(self,sha1):

        buildObj = None
        successfulBuildFound = False
        buildNums = self.buildExists(sha1)

        if buildNums:
            for buildNum in buildNums:
                buildObj = self.__JenkinsCommand.getBuild(buildNum)
                if self.__JenkinsCommand.buildStatus(buildObj) == "SUCCESS":
                    successfulBuildFound = True
                    break;
            if not successfulBuildFound:
                buildObj = None

        if not buildObj:
            buildObj = self.__startNewBuild(sha1)
        
        self.__buildObj = buildObj

    def getBuildArtifacts(self):

        return self.__JenkinsCommand.getBuildArtifacts(self.__buildObj)

    def getBuildURL(self):

        k = None
        art = self.__JenkinsCommand.getBuildArtifacts(self.__buildObj)
        for key in art.keys():
            if self.__buildName in key:
                k = key
                break
        
        if not k:
            raise xenrt.XRTError('Build URL not found')
        buildURL = art[k].url
        return buildURL

    def __startNewBuild(self,sha1):

        buildParams = {}
        buildParams['revision'] = sha1
        return self.__JenkinsCommand.invokeBuild(buildParams)
  
    def isBuildRunning(self):

        #returns true or false
        return self.__JenkinsCommand.buildRunning(self.__buildObj)

    def buildStatus(self):

        return self.__JenkinsCommand.buildStatus(self.__buildObj)

    def getBuildObj(self):
   
        return self.__buildObj
 
class BuildObserver(xenrt.XRTThread):
    __metaclass__ = ABCMeta
    _buildObj = None
 
    def __init__(self,timeout = 3600):

        self.__timeout = timeout
        xenrt.XRTThread.__init__(self)

    @abstractmethod
    def setBuildParams(self,build):
        pass

    def run(self):

        startTime = time.time()
        
        while 1: 
            if self.buildRunning():
                time.sleep(10)
            else: 
                break

            if (time.time() - startTime > self.__timeout):
                break

    @abstractmethod 
    def buildRunning(self):
        pass

class JenkinsObserver(BuildObserver):

    def startObserving(self):

        if not self.isAlive():
            self.start()
        else:
            raise xenrt.XRTError("Jenkins build observer is already running")

    def buildRunning(self):

        return self._jenkinsBuild.isBuildRunning()

    def setBuildParams(self,JenkinsBuild):

        self._jenkinsBuild = JenkinsBuild

    def waitToFinish(self):

        if not self.isAlive():
            return
        self.join()

class InstallBuild(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def downloadBuild(self):
        pass

    @abstractmethod
    def installBuild(self):
        pass

class InstallMarvin(InstallBuild):
   
    def __init__(self,sha1,workDir = None):

        self.__sha1 = sha1
        if not workDir:
            self.__workDir = xenrt.TEC().tempDir()
 
    def downloadBuild(self):

        observer = JenkinsObserver()
        jenkinsBuild = JenkinsBuild()
        jenkinsBuild.findBuild(self.__sha1)
        jenkinsBuild.attachObserver(observer)
        observer.waitToFinish()
        buildURL = jenkinsBuild.getBuildURL()
        os.system('cd %s && wget %s' % (self.__workDir, buildURL))
        self.__filename = listdir(self.__workDir)[0]
  
    def installBuild(self):

        self.downloadBuild()
        subprocess.Popen(["easy_install","--install-dir=%s" % self.__workDir,self.__filename],env={"PYTHONPATH":self.__workDir})
        eggFiles = [f for f in listdir(self.__workDir) if '.egg' in f]
        for f in eggFiles: sys.path.insert(0,self.__workDir + f)
