#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a Native Windows host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, urllib, os.path

import xenrt


__all__ = ["createHost",
           "WindowsHost",
           "hostFactory"]

def createHost(id=0,
               version=None,
               pool=None,
               name=None,
               dhcp=True,
               license=True,
               diskid=0,
               diskCount=1,
               productType=None,
               productVersion=None,
               withisos=False,
               noisos=None,
               overlay=None,
               installSRType=None,
               suppackcds=None,
               addToLogCollectionList=False,
               noAutoPatch=False,
               disablefw=False,
               cpufreqgovernor=None,
               usev6testd=True,
               ipv6=None,
               noipv4=False,
               basicNetwork=True,
               extraConfig=None,
               vHostName=None):

    if vHostName:
        raise xenrt.XRTError("Nested hosts not supported for this host type")

    machine = str("RESOURCE_HOST_%s" % (id))

    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    xenrt.GEC().startLogger(m)

    if not productVersion:
        productVersion = xenrt.TEC().lookup("HYPERV_DISTRO", "ws12r2-x64")

    host = WindowsHost(m, productVersion=productVersion, productType=productType)

    host.install()

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    return host

def hostFactory(productVersion):
    return WindowsHost

class WindowsHost(xenrt.GenericHost):

    def __init__(self,
                 machine,
                 productType="unknown",
                 productVersion="unknown",
                 productRevision="unknown"):
        xenrt.GenericHost.__init__(self,
                             machine=machine,
                             productType=productType,
                             productVersion=productVersion,
                             productRevision=productRevision)
        self.domainController=None
        try:
            xenrt.GEC().dbconnect.jobctrl("mupdate", [self.getName(), "WINDOWS", "yes"])
        except:
            pass

    def install(self):
        self.windows = True
        self.distro = self.productVersion
        if xenrt.TEC().lookup("EXISTING_WINDOWS", False, boolean=True):
            return
        self.installWindows()

    def existing(self):
        self.windows=True
        # TODO actually detect this
        self.distro = "ws12r2-x64"
        return

    def installWindows(self):
        # Construct a PXE target
        pxe1 = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe1.setSerial(serport, serbaud)
        pxe2 = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe2.setSerial(serport, serbaud)
        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe1.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe1.addEntry("local", boot="local")

        pxe1.addEntry("ipxe", boot="ipxe")
        pxe1.setDefault("ipxe")
        pxe1.writeOut(self.machine)

        wipe = pxe2.addEntry("wipe", boot="memdisk")
        wipe.setInitrd("%s/wininstall/netinstall/wipe/winpe.iso" % (xenrt.TEC().lookup("LOCALURL")))
        wipe.setArgs("iso raw")
        
        wininstall = pxe2.addEntry("wininstall", boot="memdisk")
        wininstall.setInitrd("%s/wininstall/netinstall/%s/winpe/winpe.iso" % (xenrt.TEC().lookup("LOCALURL"), self.productVersion))
        wininstall.setArgs("iso raw")
       

        pxe2.setDefault("wipe")
        filename = pxe2.writeOut(self.machine, suffix="_ipxe")
        ipxescript = """set 209:string pxelinux.cfg/%s
chain tftp://${next-server}/pxelinux.0
""" % os.path.basename(filename)
        pxe2.writeIPXEConfig(self.machine, ipxescript)

        self.machine.powerctl.cycle()
        # Wait for the iPXE file to be accessed for wiping - once it has, we can switch to proper install
        pxe1.waitForIPXEStamp(self.machine)
        xenrt.sleep(30) # 30s to allow PXELINUX to load
        pxe2.setDefault("wininstall")
        pxe2.writeOut(self.machine, suffix="_ipxe")
        pxe2.writeIPXEConfig(self.machine, ipxescript)
        
        # Wait for the iPXE file to be accessed again - once it has, we can clean it up ready for local boot
        
        pxe1.waitForIPXEStamp(self.machine)
        xenrt.sleep(30) # 30s to allow PXELINUX to load
        pxe2.clearIPXEConfig(self.machine)
        pxe1.setDefault("local")
        pxe1.writeOut(self.machine)

        # Wait for Windows to be ready
        self.waitForDaemon(7200)
        try:
            self.xmlrpcUpdate()
        except:
            xenrt.TEC().logverbose("Warning - could not update XML/RPC daemon")

        if self.xmlrpcFileExists("c:\\xenrtinstalled.stamp"):
            raise xenrt.XRTFailure("Installation stamp file already exists, this must be a previous installation")
        self.xmlrpcWriteFile("c:\\xenrtinstalled.stamp", "Installed")

        self.xmlrpcWriteFile("c:\\onboot.cmd", "echo Booted > c:\\booted.stamp")
        self.winRegAdd("HKLM",
                       "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                       "Run",
                       "Booted",
                       "SZ",
                       "c:\\onboot.cmd")
        self.installAdditionalNICDrivers()
        # Disable NLA requirement for RDP
        self.xmlrpcExec("""(Get-WmiObject -class "Win32_TSGeneralSetting" -Namespace root\\cimv2\\terminalservices -ComputerName $env:ComputerName -Filter "TerminalName='RDP-tcp'").SetUserAuthenticationRequired(0)""", powershell=True)

    def installAdditionalNICDrivers(self):
        drivers = self.lookup("WINDRIVERS", None)
        if not drivers:
            return

        driverlist = drivers.split(",")
        for d in driverlist:
            (archive, inf, pci) = d.split(":",2)
            self.xmlrpcUnpackTarball("%s/%s.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE"), archive), "c:\\")
            self.devcon("update \"c:\\%s\\%s\" \"%s\"" % (archive, inf, pci))


    def reboot(self):
        self.softReboot()

    def softReboot(self):
        self.xmlrpcExec("del c:\\booted.stamp")
        deadline = xenrt.util.timenow() + 1800

        self.xmlrpcReboot()

        while True:
            try:
                if self.xmlrpcFileExists("c:\\booted.stamp"):
                    break
            except:
                pass
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Timed out waiting for windows reboot")
            xenrt.sleep(15)

    def checkHealth(self, unreachable=False, noreachcheck=False, desc=""):
        pass

    def joinDefaultDomain(self):
        self.rename(self.getName())
        self.xmlrpcExec("netsh advfirewall set domainprofile state off")
        ad = xenrt.getADConfig()
        self.xmlrpcExec("netdom join %s /domain:%s /userd:%s\\%s /passwordd:%s" % (self.getName(), ad.domain, ad.domainName, ad.adminUser, ad.adminPassword))
        self.softReboot()

    def reconfigureToStatic(self, ad=False):
        data = self.getWindowsIPConfigData()
        ifname = [x for x in data.keys() if data[x].has_key('IPv4 Address') and (data[x]['IPv4 Address'] == self.machine.ipaddr or data[x]['IPv4 Address'] == "%s(Preferred)" % self.machine.ipaddr)][0]
        netcfg = xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT"])
        cmd = "netsh interface ip set address \"%s\" static %s %s %s 1" % (ifname,
                                                                           self.machine.ipaddr,
                                                                           netcfg['SUBNETMASK'],
                                                                           netcfg['GATEWAY'])

        ref = self.xmlrpcStart(cmd)
        deadline = xenrt.timenow() + 120

        while True:
            try:
                if self.xmlrpcPoll(ref):
                    break
            except:
                pass
            if xenrt.timenow() > deadline:
                raise xenrt.XRTError("Timed out setting IP to static")
            xenrt.sleep(5)

        if ad:
            dns = xenrt.getADConfig().dns
        else:
            dns = xenrt.TEC().config.lookup("XENRT_SERVER_ADDRESS")
        cmd = "netsh interface ipv4 add dnsservers \"%s\" %s" % (ifname, dns)
        self.xmlrpcExec(cmd)

    def disableOtherNics(self):
        data = self.getWindowsIPConfigData()
        eths = [x for x in data.keys() if data[x].has_key('IPv4 Address') and not (data[x]['IPv4 Address'] == self.machine.ipaddr or data[x]['IPv4 Address'] == "%s(Preferred)" % self.machine.ipaddr)]
        for e in eths:
            cmd = "netsh interface set interface \"%s\" disabled" % (e)
            try:
                self.xmlrpcExec(cmd)
            except:
                pass
            
    def getDomainController(self):
        if not self.domainController:
            ad = xenrt.getADConfig()
            self.domainController = xenrt.lib.generic.StaticOS(ad.dcDistro, ad.dcAddress)
            self.domainController.os.enablePowerShellUnrestricted()
        return self.domainController

    def isEnabled(self):
        return True


