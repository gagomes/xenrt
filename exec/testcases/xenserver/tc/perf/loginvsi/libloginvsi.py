import xenrt
from xenrt.lazylog import *

__all__ = ["LoginVSI"]

class LoginVSI(object):
    """Class that provides an interface for creating, controlling and observing a LoginVSI instance inside a VM"""

    def __init__(self, dataServerGuest, targetGuest, version="4.1.3", shareFolderName = "VSIShare"):
        self.dataServerGuest = dataServerGuest
        self.targetGuest = targetGuest
        self.version = version
        self.shareFolderName = shareFolderName
        self.shareFolderPath =r"c:\%s" % self.shareFolderName
        self.shareFolderNetworkPath = r"\\%s\%s" % (self.dataServerGuest.getIP(), self.shareFolderName)
        self.vsishareDrive = "S"
        self.vsisharePath = "%s:" % self.vsishareDrive

        self.initdistfileVars()

    def initdistfileVars(self):
        self.config = { "distfileDrive"     : "Z",
                        "officeSetup"       : "officeSetup\off2k7\setup.exe",
                        "officeSetupConfig" : "officeSetup\config.xml",
                        "dataserverZipFile" : "dataserver\vsishareFiles.zip",
                        "7zipExe"           : "7-Zip\7z.exe",
                        "targetSetup"       : "target\lib\VSITarget.cmd"
                        }

        if self.version=="4.1.3":
            self.config.update({"distfileLocation" : r"\\%s\share\vol\xenrtdata\distfiles\performance\vsi413\xenrtFiles"% xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")})
        else:
            warning("Unsupported LoginVSI version")

    def _mapLoginVSIdistfiles(self, guest):
        guest.xmlrpcMapDrive(self.config["distfileLocation"], self.config["distfileDrive"])

    def _installOffice(self, guest):
        setupFile = "%s:\%s" % (self.config["distfileDrive"], self.config["officeSetup"])
        configFile = "%s:\%s" % (self.config["distfileDrive"], self.config["officeSetupConfig"])
        guest.xmlrpcExec(r"start /w %s /config %s" % (setupFile, configFile), timeout=1200)

    def _installVSIShare(self, guest):
        guest.xmlrpcExec(r"mkdir c:\%s" % self.shareFolderName)
        guest.xmlrpcExec(r"net share %s=%s" % (self.shareFolderName,self.shareFolderPath))
        guest.xmlrpcExec(r"icacls %s /grant:r Everyone:(OI)(CI)F /T /C " % (self.shareFolderPath))

    def _installDataServer(self, guest):
        guest.xmlrpcExec(r"%s x -o%s -y -bd %s" % (self.config["7zipExe"], self.shareFolderPath, self.config["dataserverZipFile"]))
        # TODO - configure ini files.

    def _mapVSIShareToDrive(self, guest):
        guest.xmlrpcMapDrive(self.shareFolderNetworkPath, self.vsishareDrive)

    def _createSubstPaths(self, guest):
        guest.xmlrpcExec(r"subst h: /D", level=xenrt.RC_OK)
        guest.xmlrpcExec(r"subst h: %Temp%")
        guest.xmlrpcExec(r"subst g: /D", level=xenrt.RC_OK)
        guest.xmlrpcExec(r"subst g: %s\_VSI_Content" %(vsi.vsisharePath))

    def _installTarget(self, guest):
        guest.xmlrpcExec(r'setx vsishare "%s"' % (self.vsisharePath))
        guest.xmlrpcExec(r'%s 1 1 1 1 1 "LoginVSI"' % self.config["targetSetup"])

    def setupDataServer(self):
        self._mapLoginVSIdistfiles(self.dataServerGuest)
        self._installOffice(self.dataServerGuest)
        self._installVSIShare(self.dataServerGuest)
        self._installDataServer(self.dataServerGuest)

    def setupTarget(self):
        if self.dataServerGuest != self.targetGuest:
            self._mapLoginVSIdistfiles(self.targetGuest)
            self._installOffice(self.targetGuest)
        self._mapVSIShareToDrive(self.targetGuest)
        self._installTarget(self.targetGuest)
        self._createSubstPaths(guest)

    def installLoginVSI(self):
        self.setupDataServer()
        self.setupTarget()
