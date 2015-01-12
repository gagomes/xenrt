# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on windows signed components 
#

import string
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

    @abstractmethod
    def verifySignature(self,guest,testFile):
        xenrt.TEC().logverbose("signtool is verifying the %s build" % (testFile))
        try:
            guest.xmlrpcExec("c:\\signtool.exe verify /pa /v %s" % (testFile),
                                   returndata=True)
        except Exception, e:
            xenrt.TEC().logverbose("signtool fails to verify the build %s " % (testFile))
            raise xenrt.XRTFailure("%s build is not digitally signed and thus cannot be"
                                   " installed on VM. " % (testFile))
        xenrt.TEC().logverbose("The %s build is digitally signed with valid certificate" % (testFile))

    @abstractmethod
    def getCertExpiryDate(self,guest,testFile):
        """ Returns the certificate expiry date of signed exe"""
        data = guest.xmlrpcExec("c:\\signtool.exe verify /pa /v %s" % (testFile),
                                   returndata=True)
        s = data.split("Issued to: Citrix")[1].split("Expires: ")[1]
        expiryDate = s[:s.index("SHA1")].strip()
        xenrt.TEC().logverbose("Build Certificate expires on %s " % (expiryDate))

        # Change the date format to 'dd-mm-yy'
        expiryDate=datetime.strptime(expiryDate,"%a %b %d %H:%M:%S %Y").strftime("%m-%d-%y")
        return expiryDate

    @abstractmethod
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

    def verifySignature(self,guest,testFile):
        super(SignedXenCenter,self).verifySignature(guest,testFile)

    def getCertExpiryDate(self,guest,testFile):
        return super(SignedXenCenter,self).getCertExpiryDate(guest,testFile)

    def changeGuestDate(self,guest,newDate):
        super(SignedXenCenter,self).changeGuestDate(guest,newDate)

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

    def verifySignature(self,guest,testFile):
        super(SignedWindowsTools,self).verifySignature(guest,testFile)

    def getCertExpiryDate(self,guest,testFile):
        return super(SignedWindowsTools,self).getCertExpiryDate(guest,testFile)

    def changeGuestDate(self,guest,newDate):
        super(SignedWindowsTools,self).changeGuestDate(guest,newDate)
