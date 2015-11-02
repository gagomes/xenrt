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

import xenrt, xenrt.lib.nativewindows


__all__ = ["createHost",
           "hostFactory",
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

    host = HyperVHost(m, productVersion=productVersion, productType=productType)

    host.cloudstack = extraConfig.get("cloudstack", False)

    host.install()

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    if basicNetwork:
        host.createBasicNetwork()

    return host

def hostFactory(productVersion):
    return HyperVHost

class HyperVHost(xenrt.lib.nativewindows.WindowsHost):

    def install(self):
        self.windows = True
        if xenrt.TEC().lookup("EXISTING_HYPERV", False, boolean=True):
            return
        self.installWindows()
        self.installHyperV()

    def existing(self):
        return

    def createBasicNetwork(self):
        self.reconfigureToStatic(ad=self.cloudstack)
        self.disableOtherNics()
        self.createVirtualSwitch(0)
        if self.cloudstack:
            self.joinDefaultDomain()
            self.setupDomainUserPermissions()
            self.createCloudStackShares()
            self.enableMigration()

    def installHyperV(self):
        if self.productVersion.startswith("hvs"):
            needReboot = False
            features = ["RSAT-Hyper-V-Tools", "RSAT-AD-Powershell"]
        else:
            needReboot = True
            features = ["Hyper-V", "RSAT-Hyper-V-Tools", "RSAT-AD-Powershell"]
        
        for i in features:
            xenrt.TEC().logverbose(self.xmlrpcExec("Get-WindowsFeature -Name %s" % i, powershell=True, returndata=True))
            xenrt.TEC().logverbose(self.xmlrpcExec("Install-WindowsFeature -Name %s" % i, powershell=True, returndata=True))
            xenrt.TEC().logverbose(self.xmlrpcExec("Get-WindowsFeature -Name %s" % i, powershell=True, returndata=True))

        if needReboot:
            self.softReboot()

    def enableMigration(self):
        self.hypervCmd("Enable-VMMigration")
        self.hypervCmd("Set-VMHost -VirtualMachineMigrationAuthenticationType Kerberos")
        self.hypervCmd("Set-VMHost -UseAnyNetworkForMigration $true")
        self.enableDialIn()
        self.softReboot()

    def enableDialIn(self):
        myhost = self.xmlrpcGetEnvVar("COMPUTERNAME")
        script = """$ErrorActionPreference = "Stop"
Get-ADComputer %s | Set-AdObject -Replace @{msnpallowdialin=$true}
Get-ADComputer %s -Properties msnpallowdialin | Select-Object -ExpandProperty msnpallowdialin
""" % (myhost, myhost)
        xenrt.TEC().logverbose(self.getDomainController().os.execCmd(script, powershell=True, returndata=True))

    def createVirtualSwitch(self, eth):
        ps = """Import-Module Hyper-V
$ethernet = Get-NetAdapter | where {$_.MacAddress -eq "%s"}
New-VMSwitch -Name externalSwitch -NetAdapterName $ethernet.Name -AllowManagementOS $true -Notes 'Parent OS, VMs, LAN'
""" % self.getNICMACAddress(eth).replace(":","-")

        self.xmlrpcWriteFile("c:\\createvirtualswitch.ps1", ps)
        self.enablePowerShellUnrestricted()
        cmd = "powershell.exe c:\\createvirtualswitch.ps1"
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
        

    def checkHealth(self, unreachable=False, noreachcheck=False, desc=""):
        pass

    def tailorForCloudStack(self, msi):
        if self.xmlrpcFileExists("c:\\cloudTailored.stamp"):
            return
        self.installCloudAgent(msi)
        self.xmlrpcWriteFile("c:\\cloudTailored.stamp", "Tailored")

    def setupDomainUserPermissions(self):
        ad = xenrt.getADConfig()
        self.xmlrpcExec("net localgroup Administrators %s\\%s /add" % (ad.domainName, ad.adminUser))
        self.xmlrpcExec("net localgroup \"Hyper-V Administrators\" %s\\%s /add" % (ad.domainName, ad.adminUser))

        self.xmlrpcSendFile("%s/data/tests/hyperv/logonasservice.ps1" % xenrt.TEC().lookup("XENRT_BASE"), "c:\\logonasservice.ps1")
        self.enablePowerShellUnrestricted()
        self.xmlrpcExec("powershell.exe c:\\logonasservice.ps1 \"%s\\%s\"" % (ad.domainName, ad.adminUser))

    def installCloudAgent(self, msi):
        ad = xenrt.getADConfig()
        
        if msi.endswith(".msi"):
            self.xmlrpcSendFile(msi, "c:\\hypervagent.msi")
            self.xmlrpcExec("msiexec /i c:\\hypervagent.msi /quiet /qn /norestart /log c:\\cloudagent-install.log SERVICE_USERNAME=%s\\%s SERVICE_PASSWORD=%s" % (ad.domainName, ad.adminUser, ad.adminPassword))
        elif msi.endswith(".zip"):
            tempDir = xenrt.TEC().tempDir()
            xenrt.command("unzip %s -d %s" % (msi, tempDir))
            self.xmlrpcCreateDir("c:\\cshyperv")
            self.xmlrpcSendRecursive(tempDir, "c:\\cshyperv")
            self.xmlrpcExec("c:\\cshyperv\\AgentShell.exe --install -u %s\\%s -p %s" % (ad.domainName, ad.adminUser, ad.adminPassword))
            data = self.hypervCmd("New-SelfSignedCertificate -DnsName apachecloudstack -CertStoreLocation Cert:\\LocalMachine\\My | Format-Wide -Property Thumbprint -autosize").strip()
            thumbprint = data.splitlines()[-1]
            self.xmlrpcExec("netsh http add sslcert ipport=0.0.0.0:8250 certhash=%s appid=\"{727beb1c-6e7c-49b2-8fbd-f03dbe481b08}\"" % thumbprint)
        else:
            raise xenrt.XRTError("Unknown cloud agent file %s" % os.path.basename(msi))

    def createCloudStackShares(self):
        self.xmlrpcCreateDir("c:\\storage")
        self.xmlrpcCreateDir("c:\\storage\\primary")
        self.xmlrpcCreateDir("c:\\storage\\secondary")
        self.xmlrpcExec("net share storage=c:\\storage /unlimited /GRANT:EVERYONE,FULL")
        self.xmlrpcExec("icacls c:\\storage /grant Users:(OI)(CI)F")

    def isEnabled(self):
        return True

    def getNIC(self, assumedid):
        """ Return the product enumeration name (e.g. "eth2") for the
        assumed enumeration ID (integer)"""
        mac = self.getNICMACAddress(assumedid)
        mac = xenrt.util.normaliseMAC(mac)
        out = self.xmlrpcExec("Get-NetAdapter | where {$_.MacAddress -eq \"%s\"} | Format-List -Property Name" % mac.replace(":", "-"), powershell=True, returndata=True)
        for l in out.splitlines():
            m = re.match("Name : (.+)", l.strip())
            if m and not m.group(1).startswith("vEthernet"):
                return m.group(1)
        raise xenrt.XRTError("Could not find interface with MAC %s" % (mac))

    def createNetworkTopology(self, topology):
        """Create the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        if not physList:
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        # configure single nic non vlan jumbo networks
        requiresReboot = False
        has_mgmt_ip = False
        usedEths = []
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            xenrt.TEC().logverbose("Processing p=%s" % (p,))
            # create only on single nic non valn nets
            if len(nicList) == 1  and len(vlanList) == 0:
                eth = self.getNIC(nicList[0])
                usedEths.append(nicList[0])
                xenrt.TEC().logverbose("Processing eth%s: %s" % (eth, p))
                #make sure it is up

                if mgmt or storage:
                    #use the ip of the mgtm nic on the list as the default ip of the host
                    if mgmt:
                        mode = mgmt
                        usegw = True
                    else: 
                        mode = storage
                        usegw = False

                    # Enable this network device

                    if mode == "dhcp":
                        xenrt.TEC().logverbose("DHCP not supported for advanced windows network configurations, using static") 
                        mode = "static"
                   
                    if mode == "static":
                        # Configure this device for static
                        xenrt.TEC().logverbose("Configuring %s to static" % eth)
                        newip, netmask, gateway = self.getNICAllocatedIPAddress(nicList[0])
                        cmd = "netsh interface ip set address \"%s\" static %s %s %s 1" % (eth, newip, netmask, gateway)
                        self.xmlrpcExec(cmd)
                        cmd = "netsh interface ipv4 set interface \"%s\" ignoredefaultroutes=%s" % (eth, 'disabled' if usegw else 'enabled')
                        self.xmlrpcExec(cmd)
                    
                    #read final ip in eth
                    # newip = code to get IP for eth
                    if newip and len(newip)>0:
                        xenrt.TEC().logverbose("New IP %s for host %s on eth%s" % (newip, self, eth))
                        if mgmt:
                            self.machine.ipaddr = newip
                            has_mgmt_ip = True
                    else:
                        raise xenrt.XRTError("Wrong new IP %s for host %s on eth%s" % (newip, self, eth))

                if vms:
                    self.createVirtualSwitch(nicList[0])


            if len(nicList) > 1:
                raise xenrt.XRTError("Can't create bond on %s using %s" %
                                       (network, str(nicList)))
            if len(vlanList) > 0:
                raise xenrt.XRTError("Can't create vlan on %s using %s" %
                                       (network, str(vlanList)))

        if len(physList)>0:
            if not has_mgmt_ip:
                raise xenrt.XRTError("The network topology did not define a management IP for the host")
        
        allEths = [0]
        allEths.extend(self.listSecondaryNICs())

        for e in allEths:
            if e not in usedEths:
                eth = self.getNIC(e)
                try:
                    self.hypervCmd("Get-NetAdapter -Name \"%s\" | Disable-NetAdapter -Confirm:$false" % eth)
                except:
                    pass

        self.getWindowsIPConfigData()
        if self.cloudstack:
            self.joinDefaultDomain()
            self.setupDomainUserPermissions()
            self.createCloudStackShares()
            self.enableMigration()

    def disableOtherNics(self):
        data = self.getWindowsIPConfigData()
        eths = [x for x in data.keys() if data[x].has_key('IPv4 Address') and not (data[x]['IPv4 Address'] == self.machine.ipaddr or data[x]['IPv4 Address'] == "%s(Preferred)" % self.machine.ipaddr)]
        for e in eths:
            try:
                self.hypervCmd("Get-NetAdapter -Name \"%s\" | Disable-NetAdapter -Confirm:$false" % e)
            except:
                pass
        self.getWindowsIPConfigData()
            
    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""
        pass

    def arpwatch(self, iface, mac, timeout=600, level=xenrt.RC_FAIL):
        """Monitor an interface (or bridge) for an ARP reply"""

        deadline = xenrt.util.timenow() + timeout

        while True:
            ip = self.checkLeases(mac)
            if ip:
                break
            xenrt.sleep(20)
            if xenrt.util.timenow() > deadline:
                xenrt.XRT("Timed out monitoring for guest DHCP lease", level, data=mac)

        return ip

    def hypervCmd(self, cmd):
        script = "$ErrorActionPreference = \"Stop\"\nImport-Module Hyper-V\n%s" % cmd
        try:
            data = self.xmlrpcExec(script, powershell=True, returndata=True)
        except:
            xenrt.TEC().logverbose("Exception running %s" % cmd)
            raise
        xenrt.TEC().logverbose(data)
        return data

    def getCDPath(self, isoname):
        if self.xmlrpcFileExists("c:\\isos\\%s" % isoname):
            return "c:\\isos\\%s" % isoname
        try:
            self.xmlrpcExec("mkdir c:\\isos")
        except:
            pass
        try:
            self.xmlrpcFetchFile("%s/%s" % (xenrt.TEC().lookup("EXPORT_ISO_HTTP"), isoname), "c:\\isos\\%s" % isoname)
            return "c:\\isos\\%s" % isoname
        except:
            return None

    def getPrimaryBridge(self):
        return "externalSwitch"

    def guestFactory(self):
        return xenrt.lib.hyperv.guest.Guest

    def getFQDN(self):
        return "%s.%s" % (self.xmlrpcGetEnvVar("COMPUTERNAME"), xenrt.getADConfig().domain)

    def enableDelegation(self, remoteHost, service):
        remote = remoteHost.xmlrpcGetEnvVar("COMPUTERNAME")
        myhost = self.xmlrpcGetEnvVar("COMPUTERNAME")
        ad = xenrt.getADConfig()
        script = """$ErrorActionPreference = "Stop"
Get-ADComputer %s | Set-AdObject -Add @{"msDS-AllowedToDelegateTo"="%s/%s","%s/%s.%s"}
Get-ADComputer %s -Properties msDS-AllowedToDelegateTo | Select-Object -ExpandProperty msDs-AllowedToDelegateTo
""" % (myhost, service, remote, service, remote, ad.domain, myhost)
        xenrt.TEC().logverbose(self.getDomainController().os.execCmd(script, powershell=True, returndata=True))
