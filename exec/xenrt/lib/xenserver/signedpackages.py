# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on windows signed components 
#

import sys, string, traceback
from abc import ABCMeta, abstractmethod, abstractproperty
from datetime import datetime
import xenrt

class SignedComponent(object):
    """Abstract Base Class for signed windows components"""

    __metaclass__ = ABCMeta

    @abstractproperty
    def description():
        pass

    @abstractmethod
    def fetchFile(self):
        pass

    @abstractmethod
    def installPackages(self,guest):
        pass

    def verifySignature(self,guest,testFile):
        xenrt.TEC().logverbose("signtool is verifying the %s build" % (testFile))
        try:
            if guest.xmlrpcGetArch() == "amd64":
                stexe = "signtool_x64.exe"
            else:
                stexe = "signtool_x86.exe"
            guest.xmlrpcExec("c:\\signtool\\%s verify /pa /v %s" % (stexe, testFile),
                                   returndata=True)
        except Exception:
            xenrt.TEC().logverbose("The %s build is not verified and cannot be installed"
                                    " on the VM"% (testFile))
            raise
        xenrt.TEC().logverbose("The %s build is digitally signed with valid certificate" % (testFile))

    def getCertExpiryDate(self,guest,testFile):
        """ Returns the certificate expiry date of signed exe"""
        if guest.xmlrpcGetArch() == "amd64":
            stexe = "signtool_x64.exe"
        else:
            stexe = "signtool_x86.exe"
        data = guest.xmlrpcExec("c:\\signtool\\%s verify /pa /v %s" % (stexe, testFile),
                                   returndata=True)
        s = data.split("Issued to: Citrix")[1].split("Expires: ")[1]
        expiryDate = s[:s.index("SHA1")].strip()
        xenrt.TEC().logverbose("Build Certificate expires on %s " % (expiryDate))

        # Change the date format to 'dd-mm-yy'
        expiryDate=datetime.strptime(expiryDate,"%a %b %d %H:%M:%S %Y").strftime("%m-%d-%y")
        return expiryDate

    def changeGuestDate(self,guest,newDate):
        """Set the guest date to newDate"""
        xenrt.TEC().logverbose("Test tring to change the guest date to past the cert expiry date")
        try:
            guest.xmlrpcExec("sc stop w32time")
            guest.xmlrpcExec("w32tm /unregister")
        except Exception, e:
                xenrt.TEC().logverbose("Exception disabling w32time "
                                       "service: %s" % (str(e)))
        guest.xmlrpcExec("echo %s | date" % (newDate.strftime("%m-%d-%Y")))
        xenrt.TEC().logverbose("The guest date set to %s " % (newDate))

class SignedXenCenter(SignedComponent):

    def fetchFile(self):
        exe = xenrt.TEC().getFile("xe-phase-1/client_install/XenCenterSetup.exe")
        if not exe:
            raise xenrt.XRTError("Cannot find the required XenCenterSetup.exe")
        return exe

    def description(self):
        return "XenCenter"

    def installPackages(self,guest):
        guest.installCarbonWindowsGUI()

class SignedWindowsTools(SignedComponent):

    def fetchFile(self):
        msi = xenrt.TEC().getFile("xe-phase-1/client_install/installwizard.msi")
        if not msi:
            raise xenrt.XRTError("Cannot find the required installwizard.msi")
        return msi

    def description(self):
        return "WindowsDrivers"

    def installPackages(self,guest):
        guest.installDrivers()
        guest.waitForAgent(180)
        guest.reboot()
        guest.check()

