from abc import ABCMeta, abstractmethod
import xenrt
import re
import datetime

class SSFile(object):

    def __init__(self, name, location):
        self.setName(name)
        self.setLocation(location)

    def getName(self):
        return self.name

    def setName(self, name):
        self.name = name

    def getLocation(self):
        return self.location

    def setLocation(self, location):
        self.location = location

class SimpleServer(object):

    def __init__(self, port, ssFiles, guest):
        self.ssFiles = ssFiles
        self.port = port
        self.guest = guest

    def isPinged(self, wait):
        xenrt.sleep(wait)
        line = self.guest.execdom0("tail -n 1 logs/server.log")
        timeStr = re.search('(\d\d:){2}\d\d',line)
        logTime = (datetime.datetime.strptime(timeStr,'%H:%M:%S')+datetime.timedelta(seconds=wait)).time()
        nowTime = datetime.datetime.now().time()
        if logTime < nowTime:
            return False
        else:
            return True

    def moveFile(self, ssFile):
        if ssFile.location == "store/":
            self.guest.execDom("mv store/{0} {0}".format(ssFile.name))
            ssFile.location = ""
        else:
            self.guest.execDom("mv {0} store/{0}".format(ssFile.name))
            ssFile.location = "store/"

    def addFile(self, ssFile, key):
        self.ssFiles[key] = ssFile

    def removeFile(self, key):
        self.ssFiles.pop(key,None)

    def addRedirect(self, dirInit, dirRe):
        pass

    def removeRedirect(self, dir):
        pass

    def getIP(self):
        return self.guest.getIP()
        
class DotNetAgent(object):

    def __init__(self):
        self.licensedFeatures = {'VSS':VSS(),'AutoUpdate':AutoUpdate()}

    def restartAgent(self):
        pass

    def agentVersion(self):
        pass

    def getLicensedFeature(self,feature):
        ''' current features are "VSS", "AutoUpdate ''' 
        return self.licensedFeatures[feature]

class LicensedFeature(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def isLicensed(self):
        pass

    @abstractmethod
    def checkKeyPresence(self):
        pass

class ActorAbstract(LicensedFeature):


    def __init__(self, actor):
        self.setActor(actor)

    def setActor(self,actor):
        self.actor = actor

    def isActive(self):
        self.actor.isActive()

    def enable(self):
        self.actor.enable()

    def disable(self):
        self.actor.disable()

    def setURL(self):
        self.actor.setURL()

    def defaultURL(self):
        self.actor.defaultURL()

    def checkKeyPresence(self):
        self.actor.checkKeyPresence()

class ActorImp(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def isActive(self):
        pass

    @abstractmethod
    def enable(self):
        pass

    @abstractmethod
    def disable(self):
        pass

    @abstractmethod
    def setURL(self):
        pass

    @abstractmethod
    def defaultURL(self):
        pass

    @abstractmethod
    def checkKeyPresence(self):
        pass

class PoolAdmin(ActorImp):

    def isActive(self):
        pass

    def enable(self):
        pass

    def disable(self):
        pass

    def setURL(self):
        pass

    def defaultURL(self):
        pass

    def checkKeyPresence(self):
        pass

class VMUser(ActorImp):

    def isActive(self):
        pass

    def enable(self):
        pass

    def disable(self):
        pass

    def setURL(self):
        pass

    def defaultURL(self):
        pass

    def checkKeyPresence(self):
        pass

class VSS(LicensedFeature):

    def isSnapshotPossible(self):
        pass

    def isLicensed(self):
        pass

    def checkKeyPresence(self):
        pass

class AutoUpdate(ActorAbstract):

    def checkDownloadedMSI(self):
        pass

    def comapreMSIArch(self):
        pass

    def isLicensed(self):
        pass

    def setUserVMUser(self):
        user = VMUser()
        self.setActor(user)

    def setUserPooAdmin(self):
        user = PoolAdmin()
        self.setActor(user)