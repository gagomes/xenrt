from abc import ABCMeta, abstractmethod
import xenrt

class DotNetAgent(object):

    self.licensedFeatures = {}

    def __init__():
        licensedFeatures['VSS'] = VSS()
        licensedFeatures['AutoUpdate'] = AutoUpdate()

    def restartAgent(self):
        pass

    def agentVersion(self):
        pass

    def getLicensedFeature(feature):
        ''' current features are "VSS", "AutoUpdate ''' 
        return LicensedFeature[feature]

class LicensedFeature(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def isLicensed(self):
        pass

    @abstractmethod
    def checkKeyPresence(self):
        pass

class ActorAbstract(LicensedFeature):

    self.actor = None

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