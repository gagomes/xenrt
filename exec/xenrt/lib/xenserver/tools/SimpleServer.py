import xenrt

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
        pass

    def moveFile(self, ssFile):
        pass

    def addFile(self, ssFile):
        pass

    def removeFile(self, ssFile):
        pass

    def addDir(self, ssFile):
        pass

    def removeDir(self, dir):
        pass

    def addRedirect(self, dirInit, dirRe):
        pass

    def removeRedirect(self, dir):
        pass