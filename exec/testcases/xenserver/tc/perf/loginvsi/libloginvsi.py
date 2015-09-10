import xenrt
from xenrt.lazylog import *

__all__ = ["LoginVSI"]

class LoginVSI(object):
    """Class that provides an interface for creating, controlling and observing a LoginVSI instance inside a VM"""

    def __init__(self, dataServerGuest, targetGuest, version="4.1.3", shareFolderName = "VSIShare", tailoredToRunOnGuestLogon = True):
        self.dataServerGuest = dataServerGuest
        self.targetGuest = targetGuest
        self.version = version
        self.shareFolderName = shareFolderName
        self.tailoredToRunOnGuestLogon = tailoredToRunOnGuestLogon

        self.shareFolderPath =r"c:\%s" % self.shareFolderName
        self.shareFolderNetworkPath = r"\\%s\%s" % ("127.0.0.1" if targetGuest==dataServerGuest else self.dataServerGuest.getIP(), self.shareFolderName)
        self.vsishareDrive = "S"
        self.vsisharePath = "%s:" % self.vsishareDrive

        self.initdistfileVars()

    def initdistfileVars(self):
        self.config = { "distfileDrive"     : "Z",
                        "officeSetup"       : r"officeSetup\off2k7\setup.exe",
                        "officeSetupConfig" : r"officeSetup\config.xml",
                        "dataserverZipFile" : r"dataserver\vsishareFiles.zip",
                        "dataserverZipPatch": r"dataserver\vsisharePatch_SingleVM.zip",
                        "7zipExe"           : r"7z1506-extra\7za.exe",
                        "targetSetup"       : r"target\lib\VSITarget.cmd"
                        }

        if self.version=="4.1.3":
            self.config.update({"distfileLocation" : r"\\%s\share\vol\xenrtdata\distfiles\performance\vsi413\xenrtFiles"% xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")})
        else:
            warning("Unsupported LoginVSI version")

    def _mapLoginVSIdistfiles(self, guest):
        guest.xmlrpcMapDrive(self.config["distfileLocation"], self.config["distfileDrive"])

    def _installOffice(self, guest):
        setupFile   = r"%s:\%s" % (self.config["distfileDrive"], self.config["officeSetup"])
        configFile  = r"%s:\%s" % (self.config["distfileDrive"], self.config["officeSetupConfig"])
        guest.installDotNet35()
        guest.xmlrpcExec(r"start /w %s /config %s" % (setupFile, configFile), timeout=1200)

    def _installVSIShare(self, guest):
        guest.xmlrpcExec(r"if not exist %s mkdir %s" % (self.shareFolderPath, self.shareFolderPath))
        guest.xmlrpcExec(r"net share %s=%s /GRANT:Everyone,Full" % (self.shareFolderName,self.shareFolderPath))
        guest.xmlrpcExec(r"icacls %s /grant:r Everyone:(OI)(CI)F /T /C " % (self.shareFolderPath))

    def _installDataServer(self, guest):
        zipexe  = r"%s:\%s" % (self.config["distfileDrive"], self.config["7zipExe"])
        zipfile = r"%s:\%s" % (self.config["distfileDrive"], self.config["dataserverZipFile"])
        zipPatch= r"%s:\%s" % (self.config["distfileDrive"], self.config["dataserverZipPatch"])
        guest.xmlrpcExec(r"%s x -o%s -y -bd %s" % (zipexe, self.shareFolderPath, zipfile ))
        guest.xmlrpcExec(r"%s x -o%s -y -bd %s" % (zipexe, self.shareFolderPath, zipPatch))

    def _mapVSIShareToDrive(self, guest):
        guest.xmlrpcMapDrive(self.shareFolderNetworkPath, self.vsishareDrive)
        guest.xmlrpcExec(r"icacls %s /grant:r Administrators:(OI)(CI)F /T /C " % (self.vsisharePath))

    def _createSubstPaths(self, guest):
        guest.xmlrpcExec(r"subst h: /D", level=xenrt.RC_OK)
        guest.xmlrpcExec(r"subst h: %Temp%")
        guest.xmlrpcExec(r"subst g: /D", level=xenrt.RC_OK)
        guest.xmlrpcExec(r"subst g: %s\_VSI_Content" %(self.vsisharePath))

    def _installTarget(self, guest):
        guest.xmlrpcExec(r'setx vsishare "%s"' % (self.vsisharePath))
        targetcmd = r"%s:\%s" % (self.config["distfileDrive"], self.config["targetSetup"])
        guest.xmlrpcExec(r'%s 1 1 1 1 1 "LoginVSI"' % targetcmd, level=xenrt.RC_OK) # targetcmd throws error even if all tasks are done.
        guest.xmlrpcExec(r'regedit /s %s\_VSI_Binaries\Target\IE8_RunOnce.reg' % (self.vsisharePath))
        guest.xmlrpcExec(r'regedit /s %s\_VSI_Binaries\Target\Office12.reg' % (self.vsisharePath))

    def _tailorToRunOnGuestBoot(self, guest):
        startupPath = r"C:\Users\Administrator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\LoginVSI.bat"
        startupCmdsList = [ r"net use %s: /Delete /y" % self.vsishareDrive ,
                            r"net use %s: %s"% (self.vsishareDrive, self.shareFolderNetworkPath ),
                            r"icacls %s /grant:r Administrators:(OI)(CI)F /T /C " % (self.vsisharePath),
                            r'subst H: %TEMP%',
                            r'subst G: %s\_VSI_Content' % (self.vsisharePath),
                            r'%s\_VSI_Binaries\Target\Logon.cmd' % (self.vsisharePath)  ]
        guest.xmlrpcCreateFile(startupPath, "\n".join(startupCmdsList))

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
        self._createSubstPaths(self.targetGuest)
        if self.tailoredToRunOnGuestLogon:
            self._tailorToRunOnGuestBoot(self.targetGuest)

    def installLoginVSI(self):
        self.setupDataServer()
        self.setupTarget()
