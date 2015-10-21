from abc import ABCMeta, abstractmethod
import xenrt
import re
import datetime

class SimpleServer(object):

    def __init__(self, port, guest):
        self.port = port
        self.guest = guest

    def createCatalog(self,version):
        self.guest.execguest("echo > version_%s"%version)

    def isPinged(self, startTime):
        xenrt.TEC().logverbose("-----Checking if Server with port:%s is pinged-----"%self.port)
        line = self.guest.execguest("tail -n 1 logs/server%s.log"%self.port)
        log = self.guest.execguest("cat logs/server%s.log"%self.port)
        timeRE = re.search('(\d\d:){2}\d\d',line)
        if not timeRE:
            return False
        logTime = (datetime.datetime.strptime(timeRE.group(0),'%H:%M:%S')).time()
        return logTime > startTime

    def addRedirect(self):
        self.guest.execguest("printf \"HTTP/1.1 301 Moved Permanently\\r\\nLocation: http://%s:16000\\r\\n\\r\\n\" | nc -l 15000 >/dev/null 2>&1&"%(self.getIP()), timeout=10)

    def getIP(self):
        return self.guest.getIP()

class DotNetAgent(object):

    def __init__(self, guest):
        self.guest = guest
        self.os = self.guest.getInstance().os
        self.licensedFeatures = {'VSS':VSS(self.guest,self.os),'AutoUpdate':AutoUpdate(self.guest,self.os)}

    def restartAgent(self):
        try:
            self.os.execCmd("net stop \"XenSvc\" ")
        except:
            pass
        try:
            self.os.execCmd("net start \"XenSvc\" ")
        except:
            pass


    def agentVersion(self):
        major = self.os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","MajorVersion",healthCheckOnFailure=False)
        minor = self.os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","MinorVersion",healthCheckOnFailure=False)
        micro = self.os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","MicroVersion",healthCheckOnFailure=False)
        build = self.os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","BuildVersion",healthCheckOnFailure=False)
        return ("%s.%s.%s.%s"%(str(major),str(minor),str(micro),str(build)))

    def getLicensedFeature(self,feature):
        '''VSS or AutoUpdate''' 
        x = self.licensedFeatures[feature]
        if feature == "VSS":
            assert isinstance(x, VSS)
        else:
            assert isinstance(x, AutoUpdate)
        return x


class LicensedFeature(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def isLicensed(self):
        pass

    @abstractmethod
    def checkKeyPresent(self):
        pass

class ActorAbstract(LicensedFeature):

    def setActor(self,actor):
        self.actor = actor

    def isActive(self):
        self.actor.isActive()

    def enable(self):
        self.actor.enable()

    def disable(self):
        self.actor.disable()

    def remove(self):
        self.actor.remove()

    def setURL(self,url):
        self.actor.setURL(url)

    def defaultURL(self):
        self.actor.defaultURL()

    def checkKeyPresent(self):
        self.actor.checkKeyPresent()

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
    def remove(self):
        pass

    @abstractmethod
    def setURL(self, url):
        pass

    @abstractmethod
    def defaultURL(self):
        pass

    @abstractmethod
    def checkKeyPresent(self):
        pass

class PoolAdmin(ActorImp):

    def __init__(self,guest,os):
        self.guest = guest
        self.os = os

    def isActive(self):
        host = self.guest.host
        return host.xenstoreRead("/guest_agent_features/Guest_agent_auto_update/parameters/enabled") == "1"

    def enable(self):
        host = self.guest.host
        xenrt.TEC().logverbose("-----Enabling auto update via pool-----")
        host.execdom0("xe pool-param-set uuid=%s guest-agent-config:auto_update_enabled=true"% host.getPool().getUUID())

    def disable(self):
        host = self.guest.host
        xenrt.TEC().logverbose("-----Disabling auto update via pool-----")
        host.execdom0("xe pool-param-set uuid=%s guest-agent-config:auto_update_enabled=false"% host.getPool().getUUID())

    def remove(self):
        host = self.guest.host
        xenrt.TEC().logverbose("-----Removing pool enabled key-----")
        host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_enabled"%host.getPool().getUUID())

    def setURL(self,url):
        host = self.guest.host
        xenrt.TEC().logverbose("-----Setting pool URL to %s -----"%url)
        host.execdom0("xe pool-param-set uuid=%s guest-agent-config:auto_update_url=%s"%(host.getPool().getUUID(),url))

    def defaultURL(self):
        host = self.guest.host
        xenrt.TEC().logverbose("-----Removing pool URL key-----")
        host.execdom0("xe pool-param-remove uuid=%s param-name=guest-agent-config param-key=auto_update_url"%host.getPool().getUUID())

    def checkKeyPresent(self):
        host = self.guest.host
        return host.xenstoreExists("/guest_agent_features/Guest_agent_auto_update/parameters/enabled")

class VMUser(ActorImp):

    def __init__(self,guest,os):
        self.guest = guest
        self.os = os

    def isActive(self):
            key = self.os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate")
            return key != 1

    def enable(self):
        xenrt.TEC().logverbose("-----Enabling auto update via VM-----")
        self.os.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate","DWORD",0)

    def disable(self):
        xenrt.TEC().logverbose("-----Disabling auto update via VM-----")
        self.os.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate","DWORD",1)

    def remove(self):
        xenrt.TEC().logverbose("-----Removing VM registry DisableAutoUpdate key-----")
        self.os.winRegDel("HKLM","SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate")

    def setURL(self,url):
        xenrt.TEC().logverbose("-----Setting VM URL to %s -----"%url)
        self.os.winRegAdd("HKLM","SOFTWARE\\Citrix\\XenTools","update_url","SZ","%s"%url)

    def defaultURL(self):
        xenrt.TEC().logverbose("-----Removing VM URL key-----")
        self.os.winRegDel("HKLM","SOFTWARE\\Citrix\\XenTools","update_url")

    def checkKeyPresent(self):
        try:
            key = self.os.winRegLookup("HKLM","SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate",healthCheckOnFailure=False)
            if key:
                return True
        except:
            return False

class VSS(LicensedFeature):

    def __init__(self, guest, os):
        self.guest = guest
        self.os = os

    def isSnapshotPossible(self):
        try:
            self.guest.enableVSS()
        except:
            xenrt.TEC().logverbose("-----VSS failed to enable-----")
            return False

        try:
            snapuuid = self.guest.snapshot(quiesced=True)
            xenrt.TEC().logverbose("-----VSS Snapshot succeeded-----")
            self.guest.removeSnapshot(snapuuid)
            self.guest.disableVSS()
            return True
        except:
            xenrt.TEC().logverbose("-----VSS Snapshot failed-----")
            self.guest.disableVSS()
            return False

    def isLicensed(self):
        host = self.guest.host
        return host.xenstoreRead("/guest_agent_features/VSS/licensed") == "1"

    def checkKeyPresent(self):
        host = self.guest.host
        return host.xenstoreExists("/guest_agent_features/VSS")

class AutoUpdate(ActorAbstract):

    def __init__(self, guest, os):
        self.guest = guest
        self.os = os
        self.setUserPoolAdmin()

    def checkDownloadedMSI(self):
        if self.os.fileExists("C:\\Windows\\System32\\config\\systemprofile\\AppData\\Local\\citrixguestagentx64.msi"):
            return "64"
        elif self.os.fileExists("C:\\Windows\\System32\\config\\systemprofile\\AppData\\Local\\citrixguestagentx86.msi"):
            return "86"
        else:
            return None

    def compareMSIArch(self):
        msi = self.checkDownloadedMSI()
        if msi != None:
            if msi in self.os.getArch():
                return True
        return False

    def isLicensed(self):
        host = self.guest.host
        return host.xenstoreRead("/guest_agent_features/Guest_agent_auto_update/licensed") == "1"

    def setUserVMUser(self):
        user = VMUser(self.guest,self.os)
        self.setActor(user)

    def setUserPoolAdmin(self):
        user = PoolAdmin(self.guest,self.os)
        self.setActor(user)
