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
               cpufreqgovernor=None,
               usev6testd=True,
               ipv6=None,
               noipv4=False,
               basicNetwork=True,
               extraConfig=None):

    machine = str("RESOURCE_HOST_%s" % (id))

    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    xenrt.GEC().startLogger(m)

    if not productVersion:
        productVersion = xenrt.TEC().lookup("HYPERV_DISTRO", "ws12r2-x64")

    host = HyperVHost(m, productVersion=productVersion, productType=productType)

    host.install()

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    if basicNetwork:
        host.createBasicNetwork()

    return host

class HyperVHost(xenrt.lib.nativewindows.WindowsHost):

    def install(self):
        self.windows = True
        if xenrt.TEC().lookup("EXISTING_HYPERV", False, boolean=True):
            return
        self.installWindows()
        self.installHyperV()

    def createBasicNetwork(self):
        self.joinDefaultDomain()
        self.setupDomainUserPermissions()
        self.reconfigureToStatic()
        self.createCloudStackShares()
        self.createVirtualSwitch(0)

    def installHyperV(self):
        if self.productVersion.startswith("hvs"):
            needReboot = False
            features = ["RSAT-Hyper-V-Tools"]
        else:
            needReboot = True
            features = ["Hyper-V", "RSAT-Hyper-V-Tools"]
        
        for i in features:
            xenrt.TEC().logverbose(self.xmlrpcExec("Get-WindowsFeature -Name %s" % i, powershell=True, returndata=True))
            xenrt.TEC().logverbose(self.xmlrpcExec("Install-WindowsFeature -Name %s" % i, powershell=True, returndata=True))
            xenrt.TEC().logverbose(self.xmlrpcExec("Get-WindowsFeature -Name %s" % i, powershell=True, returndata=True))

        if needReboot:
            self.softReboot()

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
        
        self.xmlrpcSendFile(msi, "c:\\hypervagent.msi")
        self.xmlrpcExec("msiexec /i c:\\hypervagent.msi /quiet /qn /norestart /log c:\\cloudagent-install.log SERVICE_USERNAME=%s\\%s SERVICE_PASSWORD=%s" % (ad.domainName, ad.adminUser, ad.adminPassword))

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
                cmd = "netsh interface ip set address \"%s\" dhcp" % (eth)
                try:
                    self.xmlrpcExec(cmd)
                except:
                    pass
                cmd = "netsh interface ipv4 set interface \"%s\" ignoredefaultroutes=enabled" % (eth)
                try:
                    self.xmlrpcExec(cmd)
                except:
                    pass

        self.joinDefaultDomain()
        self.setupDomainUserPermissions()
        self.createCloudStackShares()

    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""
        pass

