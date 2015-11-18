#
# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on ESX hosts.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import csv, os, re, string, StringIO, random, uuid
import xenrt

__all__ = ["createHost",
           "ESXHost",
           "poolFactory"]

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
               extraConfig={},
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

    machine = str("RESOURCE_HOST_%s" % (id, ))

    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    xenrt.GEC().startLogger(m)

    if productVersion:
        esxVersion = productVersion
        xenrt.TEC().logverbose("Product version specified, using %s" % esxVersion)
    elif xenrt.TEC().lookup("ESXI_VERSION", None):
        esxVersion = xenrt.TEC().lookup("ESXI_VERSION")
        xenrt.TEC().logverbose("ESXI_VERSION specified, using %s" % esxVersion)
    else:
        esxVersion = "5.0.0.update01"
        xenrt.TEC().logverbose("No version specified, using %s" % esxVersion)

    host = ESXHost(m)
    host.esxiVersion = esxVersion
    host.password = xenrt.TEC().lookup("ROOT_PASSWORD")
    if not xenrt.TEC().lookup("EXISTING_VMWARE", False, boolean=True):
        host.install()

    if extraConfig.get("virconn", True):
        host.virConn = host._openVirConn()

    if installSRType != "no":
        # Add the default SR which is installed by ESX
        sr = xenrt.lib.esx.EXTStorageRepository(host, host.getDefaultDatastore())
        sr.existing()
        host.addSR(sr)

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    if extraConfig.has_key("dc") and extraConfig.has_key("cluster"):
        host.addToVCenter(extraConfig["dc"], extraConfig["cluster"])

    if cpufreqgovernor:
        # Roughly map the Linux cpufreqgovernor names onto ESXi policy names
        nameMapping = {
            "performance": "static",
            "ondemand": "dynamic",
            "powersave": "low",
        }
        if cpufreqgovernor in nameMapping:
            policy = nameMapping[cpufreqgovernor]
        else:
            policy = cpufreqgovernor

        cur = host.getCurrentPowerPolicy()
        xenrt.TEC().logverbose("Before changing cpufreq governor: %s" % (cur,))

        host.setPowerPolicy(policy)

        cur = host.getCurrentPowerPolicy()
        xenrt.TEC().logverbose("After changing cpufreq governor: %s" % (cur,))

    return host

def poolFactory(mastertype):
    return xenrt.lib.esx.pool.ESXPool

class ESXHost(xenrt.lib.libvirt.Host):

    LIBVIRT_REMOTE_DAEMON = False
    TCPDUMP = "tcpdump-uw -p" # -p makes it not use promiscuous mode, which causes packets to be duplicated

    def __init__(self, machine, productType="esx", productVersion="esx"):
        xenrt.lib.libvirt.Host.__init__(self, machine,
                                        productType=productType,
                                        productVersion=productVersion)
        self.datacenter = None
        self.cluster = None

    def _getVirURL(self):
        return "esx://%s/?no_verify=1" % self.getIP()

    def guestFactory(self):
        return xenrt.lib.esx.guest.Guest

    # Normally it's datastore1, but sometimes you get datastore2. Not clear why.
    def getDefaultDatastore(self):
        if self.defaultsr:
            default = self.defaultsr
        else:
            # Let's return the first one we find in the list of volumes.
            default = self.execdom0("cd /vmfs/volumes && ls -d datastore* | head -n 1").strip()
        xenrt.TEC().logverbose("default sr = %s" % (default,))
        return default

    def lookupDefaultSR(self):
        return self.srs[self.getDefaultDatastore()].uuid

    def getSRNameFromPath(self, srpath):
        """Returns the name of the SR in the path.
        srpath can be the SR mountpoint, or a volume within the mountpoint.
        Returns None if the path is not one of the above."""
        r = re.match(r"\[([^\]]*)\]", srpath)
        if r is None:
            return None
        return r.group(1)

    def getSRPathFromName(self, srname):
        return "[%s]" % (srname)

    def parseListForUUID(self, command, param, value, args=""):
        """Parse the output of a vm-list etc, to get the UUID where the
        specified parameter is the specified value"""
        return self.parseListForOtherParam(command, param, value, "uuid", args)

    def parseListForOtherParam(self,
                               command,
                               param,
                               value,
                               otherparam="uuid",
                               args=""):
        """Parse the output of an "esxcli --formatter=csv" CLI call, to get one
        param's value where the specified parameter is the specified value"""
        reply = StringIO.StringIO(self.execdom0("esxcli --formatter=csv %s %s" % (command, args)).strip())
        dr = csv.DictReader(reply)
        rets = []
        for row in dr:
            if row[param] == value:
                rets.append(row[otherparam])
        if len(rets) > 1:
            xenrt.TEC().warning("Multiple results for lookup of %s %s=%s" %
                                (command, param, value))
        return rets[0]

    def minimalList(self, command, params, args=None):
        """Return a list of items returned by an "esxcli --formatter=csv" CLI call"""
        a = ["esxcli --formatter=csv", command]
        if args:
            a.append(args)
        reply = StringIO.StringIO(self.execdom0(string.join(a)).strip())
        dr = csv.DictReader(reply)
        rets = []
        for row in dr:
            rets.append(row[params])
        return rets

    # NB: what we call "bridges" below are actually portgroups
    # what we call "interfaces" are actually vmknic's

    def getBridges(self):
        """Return the list of *portgroups* on the host."""
        brs = []
        for portgroups in self.minimalList("network vswitch standard list", "Portgroups"):
            brs += portgroups.strip(",").split(",")
        if len(brs) == 0:
            return None
        return brs

    def getPrimaryBridge(self):
        """Return the first *portgroup* on the host."""
        primaryBridges = self.paramGet(param="xenrt/primarybridges", isVMkernelAdvCfg=False)
        if primaryBridges:
            primaryBridges = primaryBridges.split(",")
            if len(primaryBridges) > 1:
                xenrt.TEC().logverbose("Multiple primary bridges defined")
            return random.choice(primaryBridges)
        brs = self.getBridges()
        if brs:
            return "VM Network" if "VM Network" in brs else brs[0]

    def getBridgeInterfaces(self, bridge):
        """Return the list of *vmknics* on the host."""
        # TODO
        return ["vmk0"]

    def getDefaultInterface(self):
        """Return the first *physical nic* on the host. See output from 'esxcfg-nics -l'"""
        return "vmnic0"

    def getAssumedId(self, friendlyname):
        # NET_A -> vmnic8       esxcfg-vswitch -l
        #       -> MAC          esxcfg-nics -l
        #       -> assumedid    h.listSecondaryNICs()

        # Find out which NIC(s) are on this network
        nics = self.execcmd("esxcfg-vswitch -l | grep '^  %s ' | awk '{print $4}'" % (friendlyname)).strip().split('\n')
        xenrt.TEC().logverbose("getAssumedId (ESXHost %s): network '%s' corresponds to NICs %s" % (self, friendlyname, nics))

        def nicToAssumedId(nic):
            # Get the MAC address
            nicmac = self.execcmd("esxcfg-nics -l | grep '^%s ' | awk '{print $7}'" % (nic)).strip().split('\n')[0]
            xenrt.TEC().logverbose("getAssumedId (ESXHost %s): NIC '%s' has MAC address %s" % (self, nic, nicmac))

            # Convert MAC to assumedid
            assumedid = self.listSecondaryNICs(macaddr=nicmac)[0]
            xenrt.TEC().logverbose("getAssumedId (ESXHost %s): MAC %s corresponds to assumedid %d" % (self, nicmac, assumedid))

            return assumedid

        if not len(nics)>0:
            raise xenrt.XRTError("Could not find interface matching friendlyname %s" % (friendlyname))
        return 0 if nics[0] == "0" else nicToAssumedId(nics[0])

    def getNIC(self, assumedid):
        """ Return the product enumeration name (e.g. "vmnic0") for the
        assumed enumeration ID (integer)"""
        mac = self.getNICMACAddress(assumedid)
        mac = xenrt.util.normaliseMAC(mac)
        ieth = self.execcmd("esxcfg-nics -l | fgrep -i ' %s ' | awk '{print $1}'" % (mac)).strip()
        if ieth == '':
            raise xenrt.XRTError("Could not find interface with MAC %s" % (mac))
        else:
            xenrt.TEC().logverbose("getNIC: interface with MAC %s is %s" % (mac, ieth))
            return ieth

    def arpwatch(self, iface, mac, **kwargs):
        if xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True):
            xenrt.lib.libvirt.Host.arpwatch(self, iface, mac, **kwargs)

        xenrt.TEC().logverbose("Working out vmkernel device for iface='%s' in order to arpwatch for %s..." % (iface, mac))

        cmds = [
            """vswitch=$(esxcli network vswitch standard list | grep -B 13 "Portgroups: .*%s\(,\|$\)" | head -n 1)""" % (iface),
            """esxcli network vswitch standard list | grep -A 13 "^$vswitch\$" | fgrep "Portgroups:" | sed 's/^.*: //'""",
        ]
        networks = self.execdom0("; ".join(cmds)).strip().split(", ")
        xenrt.TEC().logverbose("Found networks %s on the vSwitch for network '%s'" % (networks, iface))
        
        vmks = []
        for network in networks:
            vmk = self.execdom0("esxcfg-vmknic -l | fgrep \"%s\" | head -n 1 | awk '{print $1}'" % (network)).strip()
            if vmk != "":
                vmks.append(vmk)

        xenrt.TEC().logverbose("Found vmkernel device(s): %s" % (vmks))

        if len(vmks) == 0:
           raise xenrt.XRTError("Couldn't find any vmkernel device on network '%s'" % iface)

        xenrt.TEC().logverbose("Using vmkernel device %s" % (vmks[0]))
        return xenrt.GenericHost.arpwatch(self, vmks[0], mac, **kwargs)

    def install(self,
                cd=None,
                primarydisk=None,
                guestdisks=["sda"],
                source="url",
                timezone="UTC",
                interfaces=[(None, "yes", "dhcp", None, None, None)],
                ntpserver=None,
                nameserver=None,
                hostname=None,
                installSRType=None,
                bootloader=None,
                overlay=None,
                suppackcds=None):

        xenrt.TEC().progress("Installing ESXi %s" % self.esxiVersion)

        workdir = xenrt.TEC().getWorkdir()

        # Get a PXE directory to put boot files in
        pxe = xenrt.PXEBoot()

        # Create an NFS directory for images, signals, etc.
        nfsdir = xenrt.NFSDirectory()

        isoname = "/usr/groups/xenrt/esx/ESXi-%s.iso" % self.esxiVersion
        esxiso = xenrt.TEC().getFile(isoname)
        if not esxiso:
            raise xenrt.XRTError("Couldn't find ISO %s" % (isoname))

        mount = xenrt.rootops.MountISO(esxiso)
        mountpoint = mount.getMount()
        pxe.copyIn("%s/*" % (mountpoint))

        # create kickstart file
        ksname = "kickstart-%s.cfg" % (self.getName())
        kspath = "%s/%s" % (workdir, ksname)
        ks = file(kspath, "w")
        kstext = """
vmaccepteula
rootpw %s
clearpart --alldrives --overwritevmfs
install --firstdisk --overwritevmfs
network --bootproto=dhcp --device=vmnic0

%%firstboot --interpreter=busybox
vim-cmd hostsvc/enable_ssh
vim-cmd hostsvc/start_ssh
vim-cmd hostsvc/enable_esx_shell
vim-cmd hostsvc/start_esx_shell
esxcli system settings advanced set -o /UserVars/SuppressShellWarning -i 1

esxcli network firewall set --enabled false
esxcli network vswitch standard policy security set --allow-promiscuous true -v vSwitch0
esxcli system settings advanced set -i 1 -o /Misc/LogToSerial
esxcli system settings advanced set -i 115200 -o /Misc/SerialBaudRate
esxcli system settings advanced set -i 1 -o /Misc/DebugLogToSerial
esxcli system settings advanced set -s NONE -o /Misc/LogPort
esxcli system settings advanced set -s COM1 -o /Misc/LogPort

%%post --interpreter=busybox
exec < /dev/console > /dev/console 2> /dev/console
touch /vmfs/volumes/remote-install-location/.xenrtsuccess
sleep 30
reboot
""" % xenrt.TEC().lookup("ROOT_PASSWORD")
        ks.write(kstext)
        ks.close()
        nfsdir.copyIn(kspath)
        xenrt.TEC().copyToLogDir(kspath, target=ksname)

        # tweak mboot config file
        origbootcfg = file("%s/%s" % (mountpoint, "boot.cfg"), "r")
        bootcfgpath = "%s/%s" % (workdir, "boot.cfg")
        bootcfg = file(bootcfgpath, "w")
        bootcfgtext = origbootcfg.read()
        bootcfgtext = re.sub(r"/", r"", bootcfgtext)        # get rid of all absolute paths...
        bootcfgtext += "prefix=%s" % pxe.makeBootPath("")   # ... and use our PXE path as a prefix instead
        bootcfgtext = re.sub(r"--- useropts\.gz", r"", bootcfgtext)        # this file seems to cause only trouble, and getting rid of it seems to have no side effects...
        bootcfgtext = re.sub(r"--- jumpstrt\.gz", r"", bootcfgtext)        # this file (in ESXi 5.5) is similar
        if self.esxiVersion < "5.5":
            deferToolsPackInstallation = False
        else:
            bootcfgtext2 = re.sub(r"--- tools.t00", r"", bootcfgtext)      # this file is too large to get over netboot from atftpd (as used in CBGLAB01), so we will install it after host-installation
            deferToolsPackInstallation = (bootcfgtext2 <> bootcfgtext)
            bootcfgtext = bootcfgtext2
        bootcfgtext = re.sub(r"(kernelopt=.*)", r"\1 debugLogToSerial=1 logPort=com1 ks=%s" %
                             ("nfs://%s%s" % (nfsdir.getHostAndPath(ksname))), bootcfgtext)
        bootcfg.write(bootcfgtext)
        bootcfg.close()
        origbootcfg.close()
        # remove the old boot.cfg (as it is read-only, it won't let you update in place)
        os.remove(os.path.join(pxe.path(), "boot.cfg"))
        pxe.copyIn(bootcfgpath)
        xenrt.TEC().copyToLogDir(bootcfgpath, target="bootcfg-%s.cfg" % (self.getName()))

        # add boot entry
        # NB: we are not actually booting a linux kernel
        pxecfg = pxe.addEntry("esx", default=1, boot="linux")
        pxecfg.linuxSetKernel("mboot.c32")
        pxecfg.linuxArgsKernelAdd("-c %s" % pxe.makeBootPath("boot.cfg"))

        chain = self.getChainBoot()
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")

        # Set up PXE for installer boot
        pxefile = pxe.writeOut(self.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))

        # Reboot the host into the installer
        self.machine.powerctl.cycle()
        xenrt.TEC().progress("Rebooted host to start installation.")

        # Monitor for installation complete
        xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                          1800,
                          desc="Installer boot on !%s" %
                          (self.getName()))

        # Boot the local disk - we need to update this before the machine
        # reboots after setting the signal flag.
        pxe.setDefault("local")
        pxe.writeOut(self.machine)

        xenrt.sleep(30)
        self.waitForSSH(900, desc="Host boot (!%s)" % (self.getName()))

        # If we skipped tools.t00 above due to tftp issues, install it now. It's just a .tar.gz file.
        if deferToolsPackInstallation:
            xenrt.TEC().progress("Manually installing tools.t00")

            toolsFile = "%s/tools.t00" % (mountpoint)

            # Use the first-named datastore to temporarily dump the file. (Alternatively, could use /tardisks?)
            firstDatastore = self.getDefaultDatastore()
            destFilePath = "/vmfs/volumes/%s/tools.t00" % (firstDatastore)
            sftp = self.sftpClient()
            try:
                sftp.copyTo(toolsFile, destFilePath)
            finally:
                sftp.close()

            self.execdom0("tar xvfz %s -C /locker/packages" % (destFilePath))
            self.execdom0("rm -f %s" % (destFilePath))

        # We're done with the ISO now
        mount.unmount()

        nfsdir.remove()

        self.installSRType = installSRType

        xenrt.TEC().progress("Completed installation of ESXi host")

    def createNetwork(self, interface, name="bridge"):
        self.execdom0("esxcli network vswitch standard add -P 128 -v %s" % (name))
        if interface:
            self.execdom0("esxcli network vswitch standard uplink add -u %s -v %s" % (interface, name))
        # Add a vmkernel interface to the vSwitch, for arpwatching traffic on this vswitch
        self.execdom0("esxcli network vswitch standard portgroup add -v %s -p \"%s-kernelport\"" % (name, name))
        self.execdom0("esxcfg-vmknic -a -i DHCP -p \"%s-kernelport\"" % (name))

    def getBridgeVSwitchName(self, eth):
        return eth.replace("vmnic","vSwitch") if eth else "vSwitchNoAdapter"

    def getNICPIF(self, assumedid):
        """ Return the PIF UUID for the assumed enumeration ID (integer)"""
        if assumedid == 0:
            mac = self.lookup("MAC_ADDRESS", None)
            if not mac:
                xenrt.TEC().logverbose("We have no record of MAC address for default interface")
                return self.getDefaultInterface()
        else:
            mac = self.lookup(["NICS", "NIC%u" % (assumedid), "MAC_ADDRESS"],
                              None)
        if not mac:
            raise xenrt.XRTError("NIC%u not configured for %s" %
                                 (assumedid, self.getName()))
        mac = xenrt.util.normaliseMAC(mac)

        # Iterate over vmnics to find a matching device
        return self.execdom0("esxcfg-nics -l | fgrep -i %s | awk '{print $1}' | head -n 1" % (mac)).strip()

    def createNetworkTopology(self, topology):
        """Create the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        # removing obsolete advance configs on ESX host
        primaryBridges = self.paramGet(param="xenrt/primarybridges", isVMkernelAdvCfg=False)
        primaryBridges = [b for b in primaryBridges.split(",") if b in self.getBridges()] if primaryBridges else []
        self.paramSet(param="xenrt/primarybridges", value=",".join(primaryBridges))

        # parse network config
        physList = self._parseNetworkTopology(topology, useFriendlySuffix=True)
        if not physList:
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        # configure single nic non vlan jumbo networks
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            xenrt.TEC().logverbose("Processing p=%s" % (p,))
            if len(nicList) < 2:
                pri_eth=None
                if len(nicList) == 1:
                    pri_eth = self.getNICPIF(nicList[0])
                    if pri_eth == '':
                        raise xenrt.XRTError("Could not find vmnic device for device %d" % (nicList[0]))

                # Set up new vSwitch if necessary
                xenrt.TEC().logverbose("Processing %s: %s" % (pri_eth, p))
                pri_vswitch = self.getBridgeVSwitchName(pri_eth)
                has_pri_vswitch = self.execdom0("esxcfg-vswitch -l | grep '^%s '|wc -l" % (pri_vswitch,)).strip() != "0"
                if not has_pri_vswitch:
                    self.createNetwork(pri_eth, name=pri_vswitch)
                if jumbo:
                    self.execdom0("esxcli network vswitch standard set -v %s -m %d" % (pri_vswitch, 9000 if jumbo==True else jumbo ))

                # Create only on single nic non vlan nets
                if (len(vlanList) == 0 or vms or mgmt) and len(nicList) == 1:
                    # Add the network to the vSwitch
                    self.execdom0("esxcli network vswitch standard portgroup add -v %s -p \"%s\"" % (pri_vswitch, friendlynetname))

                    if mgmt or storage:
                        # TODO move the "Management Network" onto this vSwitch. Not sure how to do this when there's a vmk0 using it.
                        # ESX doesn't allow same port to be used for vms as well as management. Either we create a new VMKernel port 
                        # for this purpose or use VMKernel port created along with vswitch in self.createNetwork(...).
                        raise xenrt.XRTError("unimplemented")

                    if vms:
                        xenrt.TEC().logverbose("Putting VMs on '%s' (%s)" % (friendlynetname, str(nicList)))
                        existingPrimaryBridges = self.paramGet(param="xenrt/primarybridges", isVMkernelAdvCfg=False)
                        primaryBridges = "%s,%s" % (existingPrimaryBridges,friendlynetname) if existingPrimaryBridges else friendlynetname
                        self.paramSet(param="xenrt/primarybridges", value=primaryBridges)

                # Create all VLANs
                for v in vlanList:
                    vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                    vid, subnet, netmask = self.getVLAN(vnetwork)

                    portlist = self.execdom0("esxcli --formatter=csv network vswitch standard portgroup list").strip().split("\n")
                    portlist = [t_p.split(",") for t_p in portlist]
                    portlist = [t_p[1] for t_p in portlist if pri_vswitch==str(t_p[3]) and vid==int(t_p[2])]
                    if len(portlist)>0:
                        xenrt.TEC().logverbose(" ... already exists")
                    else:
                        xenrt.TEC().logverbose("Creating VLAN '%s' on %s (%s)" % (vfriendlynetname, network, str(nicList)))
                        # Add the network to the vSwitch
                        self.execdom0("esxcli network vswitch standard portgroup add -v %s -p \"%s\"" % (pri_vswitch, vfriendlynetname))
                        self.execdom0("esxcli network vswitch standard portgroup set -v %d -p \"%s\"" % (vid, vfriendlynetname))

                    if vvms:
                        xenrt.TEC().logverbose("Putting VMs on VLAN '%s' on %s (%s)" % (vfriendlynetname, network, str(nicList)))
                        existingPrimaryBridges = self.paramGet(param="xenrt/primarybridges", isVMkernelAdvCfg=False)
                        primaryBridges = "%s,%s" % (existingPrimaryBridges,vfriendlynetname) if existingPrimaryBridges else vfriendlynetname
                        self.paramSet(param="xenrt/primarybridges", value=primaryBridges)

                    if vmgmt or vstorage:
                        raise xenrt.XRTError("unimplemented")

            if len(nicList) > 1:
                raise xenrt.XRTError("Creation of bond on %s using %s unimplemented" %
                                       (network, str(nicList)))

    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""
        pass

    def addToVCenter(self, dc=None, cluster=None):
        if not dc:
            job=xenrt.GEC().jobid() or "nojob"
            dc='dc-%s-%s' % (uuid.uuid4().hex, job)
        if not cluster:
            cluster='cluster-%s' % (uuid.uuid4().hex)
        xenrt.lib.esx.getVCenter().addHost(self, dc, cluster)
        self.datacenter=dc
        self.cluster=cluster

    def removeFromVCenter(self):
        if self.datacenter:
            xenrt.lib.esx.getVCenter().removeHost(self)
            self.datacenter=None
            self.cluster=None

    def setPowerPolicy(self, policyname):
        script = """
from pyVim.connect import Connect
si = Connect()
hostConfig = si.RetrieveContent().rootFolder.childEntity[0].hostFolder.childEntity[0].host[0]
key = None
for policy in hostConfig.config.powerSystemCapability.availablePolicy:
    if policy.shortName == "%s":
        key = policy.key

if not key:
    exit(1)

# Change to new policy
hostConfig.GetConfigManager().GetPowerSystem().ConfigurePowerPolicy(key)
""" % (policyname)
        self.execcmd("echo '%s' | python" % (script))

    def getCurrentPowerPolicy(self):
        script = """
from pyVim.connect import Connect
si = Connect()
hostConfig = si.RetrieveContent().rootFolder.childEntity[0].hostFolder.childEntity[0].host[0]

# Report existing policy
print hostConfig.GetConfigManager().GetPowerSystem().info.currentPolicy.shortName
"""
        return self.execcmd("echo '%s' | python" % (script)).strip()

    def paramGet(self, param, isVMkernelAdvCfg=False):
        try:
            if isVMkernelAdvCfg:
                return self.execdom0("esxcfg-advcfg --get %s" % (param)).strip().split(" is ")[-1]
            # User defined config
            return self.execdom0("esxcfg-advcfg --get-user-var --user-var %s" % (param)).strip()
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("advance config '%s' doesn't exist." % param)
        return None

    def paramSet(self, param, value, isVMkernelAdvCfg=False):
        if isVMkernelAdvCfg:
            self.execdom0("esxcfg-advcfg --set '%s' %s" % (value, param))
        elif not value:
            self.execdom0("esxcfg-advcfg --del-user-var --user-var %s" % (param))
        else:
            self.execdom0("esxcfg-advcfg --set-user-var '%s' --user-var %s" % (value, param))

    def getBridgeByName(self, name):
        """Return the actual bridge based on the given friendly name. """
        if not name:
            return self.getPrimaryBridge()
        if name=="NSEC" or name=="NPRI":
            raise xenrt.XRTError("Unimplemented")
        brs = self.getBridges()
        if name in brs:
            return name
        brs = [br for br in brs if name in br]
        if len(brs)==1:
            return brs[0]
        elif len(brs)>1:
            raise xenrt.XRTError("Multiple bridges found")
        return None
