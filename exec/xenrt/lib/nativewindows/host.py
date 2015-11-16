#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a Native Windows host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, urllib, os.path, xmlrpclib, shutil

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
               defaultlicense=True,
               ipv6=None,
               noipv4=False,
               basicNetwork=True,
               extraConfig=None,
               containerHost=None,
               vHostName=None,
               vHostCpus=2,
               vHostMemory=4096,
               vHostDiskSize=50,
               vHostSR=None,
               vNetworks=None,
               **kwargs):

    if containerHost != None:
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
        # Set up the ISO
        mount = xenrt.mountStaticISO(self.productVersion)
        nfsdir = xenrt.NFSDirectory()
        xenrt.command("ln -sfT %s %s/iso" % (mount, nfsdir.path()))

        os.makedirs("%s/custom" % nfsdir.path())
        shutil.copy("%s/iso/Autounattend.xml" % nfsdir.path(), "%s/custom/Autounattend.xml" % nfsdir.path())

        xenrt.command("""sed -i "s#<CommandLine>.*</CommandLine>#<CommandLine>c:\\\\\\\\install\\\\\\\\runonce.cmd</CommandLine>#" %s/custom/Autounattend.xml""" % nfsdir.path())
        shutil.copytree("%s/iso/$OEM$" % nfsdir.path(), "%s/custom/oem" % nfsdir.path())
        xenrt.command("chmod u+w %s/custom/oem/\\$1/install" % nfsdir.path())

        with open("%s/custom/oem/$1/install/runonce.cmd" % nfsdir.path(), "w") as f:
            f.write("%systemdrive%\install\python\python.cmd\r\n")
            f.write("EXIT\r\n")

        
        # First boot into winpe
        winpe = WinPE(self)
        winpe.boot()
        
        xenrt.TEC().logverbose("WinPE booted, wiping disk")
        # Wipe the disks and reboot
        winpe.xmlrpc.write_file("x:\\diskpart.txt", "list disk\nselect disk 0\nclean\nexit")
        winpe.xmlrpc.exec_shell("diskpart.exe /s x:\\diskpart.txt")
        xenrt.TEC().logverbose("Rebooting WinPE")
        winpe.reboot()

        xenrt.TEC().logverbose("WinPE rebooted, mounting shares")

        winpe.xmlrpc.exec_shell("net use y: %s\\iso" % nfsdir.getCIFSPath()) 
        winpe.xmlrpc.exec_shell("net use z: %s\\custom" % nfsdir.getCIFSPath()) 

        xenrt.TEC().logverbose("Starting installer")
        # Mount the install share and start the installer
        winpe.xmlrpc.start_shell("y:\\setup.exe /unattend:z:\\autounattend.xml /m:z:\\oem")

        # Now Construct a PXE target for local boot
        pxe = xenrt.PXEBoot()
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe.setSerial(serport, serbaud)
        chain = self.getChainBoot()
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")

        pxe.setDefault("local")
        pxe.writeOut(self.machine)

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
                                                                           data[ifname]['Subnet Mask'],
                                                                           [x for x in data[ifname]['Default Gateway'].split() if re.match("\d+\.\d+\.\d+\.\d+", x)][0])

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

    def disableOtherNics(self, ip=None):
        if not ip:
            ip = self.machine.ipaddr
        data = self.getWindowsIPConfigData()
        eths = [x for x in data.keys() if data[x].has_key('IPv4 Address') and not (data[x]['IPv4 Address'] == ip or data[x]['IPv4 Address'] == "%s(Preferred)" % ip)]
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

    def getNIC(self, assumedid):
        """ Return the product enumeration name (e.g. "Local Area Connection 3") for the
        assumed enumeration ID (integer)"""
        mac = self.getNICMACAddress(assumedid)
        mac = mac.upper().replace(':', '-')

        ipconfig = self.getWindowsIPConfigData()
        for intf in ipconfig.keys():
            if "Physical Address" in ipconfig[intf] and ipconfig[intf]['Physical Address'] == mac:
                return intf
        raise xenrt.XRTError("Could not find interface with MAC %s" % (mac))

    def createNetworkTopology(self, topology):
        """Create the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        if not physList:
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        ipconfig = self.getWindowsIPConfigData()

        # TODO Currently only supports configuring a single NIC
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            xenrt.TEC().logverbose("Processing p=%s" % (p,))
            if len(nicList) == 1 and len(vlanList) == 0:
                assumedid = nicList[0]
                intf = self.getNIC(assumedid) # e.g. "Local area connection 3"

                # Set this interface as the one to use for xmlrpc
                newip, netmask, gateway = self.getNICAllocatedIPAddress(assumedid)
                self.machine.ipaddr = newip

                # Disable all other devices
                eths = [x for x in ipconfig.keys() if x != intf]
                for e in eths:
                    cmd = "netsh interface set interface \"%s\" disabled" % (e)
                    try:
                        self.xmlrpcExec(cmd)
                    except:
                        pass

    def checkNetworkTopology(self, topology, ignoremanagement=False, ignorestorage=False, plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""
        pass

class WinPE(xenrt._WinPEBase):
    def __init__(self, host):
        super(WinPE, self).__init__()
        self.host = host
        self.ip = self.host.getIP()

    def boot(self):
        if self.host.productVersion.endswith("-x64"):
            arch = "amd64"
        else:
            arch = "x86"
        # Construct a PXE target
        pxe1 = xenrt.PXEBoot()
        serport = self.host.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.host.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe1.setSerial(serport, serbaud)
        pxe2 = xenrt.PXEBoot()
        serport = self.host.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.host.lookup("SERIAL_CONSOLE_BAUD", "115200")
        pxe2.setSerial(serport, serbaud)
    
        pxe1.addEntry("ipxe", boot="ipxe")
        pxe1.setDefault("ipxe")
        pxe1.writeOut(self.host.machine)

        winpe = pxe2.addEntry("winpe", boot="memdisk")
        winpe.setInitrd("%s/tftp/winpe/winpe-%s.iso" % (xenrt.TEC().lookup("LOCALURL"), arch))
        winpe.setArgs("iso raw")
    
        pxe2.setDefault("winpe")
        filename = pxe2.writeOut(self.host.machine, suffix="_ipxe")
        ipxescript = """set 209:string pxelinux.cfg/%s
chain tftp://${next-server}/%s
""" % (os.path.basename(filename), xenrt.TEC().lookup("PXELINUX_PATH", "pxelinux.0"))
        pxe2.writeIPXEConfig(self.host.machine, ipxescript)

        self.host.machine.powerctl.cycle()
        xenrt.sleep(60)
        self.waitForBoot()
