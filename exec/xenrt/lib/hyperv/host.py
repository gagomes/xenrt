#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a Hyper-V host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, urllib, os.path

import xenrt


__all__ = ["createHost",
           "HyperVHost"]

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
               usev6testd=True,
               ipv6=None,
               noipv4=False,
               extraConfig=None):

    machine = str("RESOURCE_HOST_%s" % (id))

    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    xenrt.GEC().startLogger(m)

    if not productVersion:
        productVersion = "ws12r2-x64"

    host = HyperVHost(m, productVersion=productVersion, productType=productType)

    host.install()

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    return host

class HyperVHost(xenrt.GenericHost):

    def install(self):
        return
        self.installWindows()
        self.installHyperV()
        self.joinDefaultDomain()
        self.setupDomainUserPermissions()
        self.reconfigureToStatic()
        self.createCloudStackShares()

    def installWindows(self):
        # Construct a PXE target
        pxe = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe.setSerial(serport, serbaud)
        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")
        
        pxe.writeIPXEConfig(self.machine, "%s/wininstall/netinstall/%s/winpe/boot.ipxe" % (xenrt.TEC().lookup("LOCALURL"), self.productVersion))
        pxe.setDefault("local")
        pxe.writeOut(self.machine)

        self.machine.powerctl.cycle()
        # Wait for the iPXE file to be accessed - once it has, we can clean it up ready for local boot
        pxe.waitForIPXEStamp(self.machine)
        pxe.clearIPXEConfig(self.machine)

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

    def installHyperV(self):
        xenrt.TEC().logverbose(self.xmlrpcExec("Get-WindowsFeature -Name Hyper-V", powershell=True, returndata=True))
        xenrt.TEC().logverbose(self.xmlrpcExec("Install-WindowsFeature -Name Hyper-V", powershell=True, returndata=True))
        xenrt.TEC().logverbose(self.xmlrpcExec("Get-WindowsFeature -Name Hyper-V", powershell=True, returndata=True))
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

    def tailorForCloudStack(self, msi):
        return
        if self.xmlrpcFileExists("c:\\cloudTailored.stamp"):
            return
        self.installCloudAgent(msi)
        self.xmlrpcWriteFile("c:\\cloudTailored.stamp", "Tailored")

    def joinDefaultDomain(self):
        self.xmlrpcExec("netsh advfirewall set domainprofile state off")
        hname = self.xmlrpcExec("hostname", returndata=True).strip().splitlines()[-1]
        ad = xenrt.TEC().lookup("AD_CONFIG")
        domain=ad['DOMAIN']
        domainName = ad['DOMAIN_NAME']
        domainUser = ad['DOMAIN_JOIN_USER']
        domainPassword = ad['DOMAIN_JOIN_PASSWORD']
        self.xmlrpcExec("netdom join %s /domain:%s /userd:%s\\%s /passwordd:%s" % (hname, domain, domainName, domainUser, domainPassword))
        self.softReboot()

    def setupDomainUserPermissions(self):
        ad = xenrt.TEC().lookup("AD_CONFIG")
        domain=ad['DOMAIN']
        domainName = ad['DOMAIN_NAME']
        domainUser = ad['DOMAIN_JOIN_USER']
        domainPassword = ad['DOMAIN_JOIN_PASSWORD']
        self.xmlrpcExec("net localgroup Administrators %s\\%s /add" % (domainName, domainUser))
        self.xmlrpcExec("net localgroup \"Hyper-V Administrators\" %s\\%s /add" % (domainName, domainUser))

        self.xmlrpcSendFile("%s/data/tests/hyperv/logonasservice.ps1" % xenrt.TEC().lookup("XENRT_BASE"), "c:\\logonasservice.ps1")
        self.enablePowerShellUnrestricted()
        self.xmlrpcExec("powershell.exe c:\\logonasservice.ps1 \"%s\\%s\"" % (domainName, domainUser))

    def reconfigureToStatic(self):
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

    def installCloudAgent(self, msi):
        ad = xenrt.TEC().lookup("AD_CONFIG")
        domain=ad['DOMAIN']
        domainName = ad['DOMAIN_NAME']
        domainUser = ad['DOMAIN_JOIN_USER']
        domainPassword = ad['DOMAIN_JOIN_PASSWORD']
        
        self.xmlrpcSendFile(msi, "c:\\hypervagent.msi")
        self.xmlrpcExec("msiexec /i c:\\hypervagent.msi /quiet /qn /norestart /log c:\\cloudagent-install.log SERVICE_USERNAME=%s\\%s SERVICE_PASSWORD=%s" % (domainName, domainUser, domainPassword))
        self.softReboot()

    def createCloudStackShares(self):
        self.xmlrpcCreateDir("c:\\pristorage")
        self.xmlrpcCreateDir("c:\\secstorage")
        self.xmlrpcExec("net share pristorage=c:\\pristorage /unlimited /GRANT:EVERYONE,FULL")
        self.xmlrpcExec("net share secstorage=c:\\secstorage /unlimited /GRANT:EVERYONE,FULL")
