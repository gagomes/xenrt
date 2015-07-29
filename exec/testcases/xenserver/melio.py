import xenrt

class TCWindowsMelioSetup(xenrt.TestCase):
    def run(self, arglist):
        
        if self.getGuest("iscsi"): 
            self.shared = True
            iscsitarget = self.getGuest("iscsi")
            iqn = iscsitarget.installLinuxISCSITarget(targetType="LIO")
            iscsitarget.createISCSITargetLun(lunid=0, sizemb=20*xenrt.KILO)
            iscsitarget.createISCSITargetLun(lunid=1, sizemb=20*xenrt.KILO)
        else:
            self.shared = False

        # Get all of the IPs
        ips = []
        i = 1
        while self.getGuest("win%d" % i):
            ips.append(self.getGuest("win%d" % i).mainip)
            i += 1

        # Set up Windows
        i = 1
        while self.getGuest("win%d" % i):
            self.setupWindows(i, ips)
            i+=1
  
        # Now run the IOCTL to refresh
        i = 1
        while self.getGuest("win%d" % i):
            self.getGuest("win%d" % i).xmlrpcExec('"C:\\Program Files\\Citrix\\Warm-Drive\\Tools\\ioctl.exe" reload_settings', returndata=True, returnerror=False)
            i+=1

    def setupWindows(self, index, ips):
        win = self.getGuest("win%d" % index)
        if self.shared:
            iscsitarget = self.getGuest("iscsi")
        else:
            iscsitarget = self.getGuest("iscsi%d" % index)
            iqn = iscsitarget.installLinuxISCSITarget(targetType="LIO")
            iscsitarget.createISCSITargetLun(lunid=0, sizemb=20*xenrt.KILO)
            iscsitarget.createISCSITargetLun(lunid=1, sizemb=20*xenrt.KILO)
        win.installWindowsMelio(renameHost=True)
        config = win.getWindowsMelioConfig()
        config['network_settings']['current']['subnet_ranges'] = " ".join(["%s/32" % x for x in ips]) 
        win.reboot()
        win.writeWindowsMelioConfig(config)
        win.enablePowerShellUnrestricted() 
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nStart-Service msiscsi", powershell=True)
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nSet-Service -Name msiscsi -StartupType Automatic", powershell=True)
        
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nNew-IscsiTargetPortal -TargetPortalAddress %s" % iscsitarget.mainip, powershell=True)
        xenrt.sleep(30)
        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nGet-IscsiTarget | Connect-IscsiTarget", powershell=True)
        xenrt.sleep(30)
        disks = win.xmlrpcListDisks()[-2:]

        if int(disks[0]) == 0:
            raise xenrt.XRTFailure("iSCSI disk has not been connected")

        win.xmlrpcExec("$ErrorActionPreference = \"Stop\"\nGet-IscsiSession | Register-IscsiSession", powershell=True)
        if not self.shared:
            for disk in disks:
                win.xmlrpcDiskpartCommand("select disk %s\nattributes disk clear readonly\nconvert gpt" % disk)
