import xenrt

class TCWindowsMelioSetup(xenrt.TestCase):
    def run(self, arglist):
        
        if self.getGuest("iscsi"): 
            self.shared = True
            iscsitarget = self.getGuest("iscsi")
            iqn = iscsitarget.installLinuxISCSITarget(targetType="LIO")
            iscsitarget.createISCSITargetLun(lunid=0, sizemb=20*xenrt.KILO)
            self.initialised = False
        else:
            self.shared = False

        i = 1
        while self.getGuest("win%d" % i):
            self.setupWindows(i)
            i+=1
    
    def setupWindows(self, index):
        win = self.getGuest("win%d" % index)
        if self.shared:
            iscsitarget = self.getGuest("iscsi")
        else:
            iscsitarget = self.getGuest("iscsi%d" % index)
            iqn = iscsitarget.installLinuxISCSITarget(targetType="LIO")
            iscsitarget.createISCSITargetLun(lunid=0, sizemb=20*xenrt.KILO)
        win.installWindowsMelio()
        win.enablePowerShellUnrestricted() 
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nStart-Service msiscsi", powershell=True)
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nSet-Service -Name msiscsi -StartupType Automatic", powershell=True)
        
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nNew-IscsiTargetPortal -TargetPortalAddress %s" % iscsitarget.mainip, powershell=True)
        xenrt.sleep(30)
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nGet-IscsiTarget | Connect-IscsiTarget", powershell=True)
        xenrt.sleep(30)
        disk = win.xmlrpcListDisks()[-1]

        if int(disk) == 0:
            raise xenrt.XRTFailure("iSCSI disk has not been connected")

        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nGet-IscsiSession | Register-IscsiSession", powershell=True)
        if not self.shared or not self.initialised:
            win.xmlrpcDiskpartCommand("select disk %s\nattributes disk clear readonly\nconvert gpt" % disk)
            self.initialised = True
