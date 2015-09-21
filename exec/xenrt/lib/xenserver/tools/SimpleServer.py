import xenrt
import re
import datetime

class SSFile(object):
    self.name = ""
    self.location = ""

    def __init__(name, location):
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
    self.ssFiles = {}
    self.port = ""
    self.guest = None

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