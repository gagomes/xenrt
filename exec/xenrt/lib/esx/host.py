#
# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on ESX hosts.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import csv, os, re, string, StringIO
import xenrt

__all__ = ["createHost",
           "ESXHost"]

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

    machine = str("RESOURCE_HOST_%s" % (id, ))

    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    xenrt.GEC().startLogger(m)

    if productVersion:
        esxVersion = productVersion
    elif xenrt.TEC().lookup("ESXI_VERSION", None):
        esxVersion = xenrt.TEC().lookup("ESXI_VERSION")
    else:
        esxVersion = "5.0.0.update01"

    host = ESXHost(m)
    host.esxiVersion = esxVersion
    host.password = xenrt.TEC().lookup("ROOT_PASSWORD")
    host.install()

    host.virConn = host._openVirConn()

    # Add the default SR which is installed by ESX
    sr = xenrt.lib.esx.EXTStorageRepository(host, "datastore1")
    sr.existing()
    host.addSR(sr)

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    if extraConfig.has_key("dc") and extraConfig.has_key("cluster"):
        host.addToVCenter(extraConfig["dc"], extraConfig["cluster"])

    return host

class ESXHost(xenrt.lib.libvirt.Host):

    LIBVIRT_REMOTE_DAEMON = False
    TCPDUMP = "tcpdump-uw"

    def __init__(self, machine, productType="esx", productVersion="esx"):
        xenrt.lib.libvirt.Host.__init__(self, machine,
                                        productType=productType,
                                        productVersion=productVersion)

    def _getVirURL(self):
        return "esx://%s/?no_verify=1" % self.getIP()

    def guestFactory(self):
        return xenrt.lib.esx.guest.ESXGuest

    def lookupDefaultSR(self):
        # TODO
        return self.srs["datastore1"].uuid

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
        # TODO
        brs = self.getBridges()
        if brs:
            return brs[0]

    def getBridgeInterfaces(self, bridge):
        """Return the list of *vmknics* on the host."""
        # TODO
        return ["vmk0"]

    def getDefaultInterface(self):
        """Return the first *physical nic* on the host. See output from 'esxcfg-nics -l'"""
        return "vmnic0"

    def arpwatch(self, iface, mac, **kwargs):
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
        bootcfgtext2 = re.sub(r"--- tools.t00", r"", bootcfgtext)          # this file is too large to get over netboot from atftpd (as used in CBGLAB01), so we will install it after host-installation
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

        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
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
            destFilePath = "/vmfs/volumes/datastore1/tools.t00"
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
        self.execdom0("esxcli network vswitch standard uplink add -u %s -v %s" % (interface, name))

    def getBridge(self, eth):
        return eth.replace("vmnic","vSwitch")

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

        physList = self._parseNetworkTopology(topology)
        if not physList:
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        # configure single nic non vlan jumbo networks
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            xenrt.TEC().logverbose("Processing p=%s" % (p,))
            # create only on single nic non vlan nets
            if len(nicList) == 1  and len(vlanList) == 0:
                pri_eth = self.getNICPIF(nicList[0])

                # Set up new vSwitch if necessary
                xenrt.TEC().logverbose("Processing %s: %s" % (pri_eth, p))
                pri_bridge = self.getBridge(pri_eth)
                has_pri_bridge = self.execdom0("esxcfg-vswitch -l | grep '^%s '|wc -l" % (pri_bridge,)).strip() != "0"
                if not has_pri_bridge:
                    self.createNetwork(pri_eth, name=pri_bridge)

                # Add the network to the vSwitch
                self.execdom0("esxcli network vswitch standard portgroup add -v %s -p \"%s\"" % (pri_bridge, friendlynetname))

                # Create a vmkernel interface on this vSwitch, to be used for arpwatching traffic on this vswitch
                self.execdom0("esxcfg-vmknic -a -i DHCP -p \"%s\"" % (friendlynetname))

                if mgmt:
                    # TODO move the "Management Network" onto this vSwitch. Not sure how to do this when there's a vmk0 using it.
                    pass

                if jumbo == True:
                    # TODO
                    pass

            if len(nicList) > 1:
                raise xenrt.XRTError("Creation of bond on %s using %s unimplemented" %
                                       (network, str(nicList)))
            if len(vlanList) > 0:
                raise xenrt.XRTError("Creation of vlan on %s using %s unimplemented" %
                                       (network, str(vlanList)))

    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""
        pass

    def addToVCenter(self, dc, cluster):
        lock = xenrt.resources.CentralResource()
        attempts = 0
        while True:
            try:
                lock.acquire("VCENTER")
                break
            except:
                xenrt.sleep(60)
                attempts += 1
                if attempts > 20:
                    raise xenrt.XRTError("Couldn't get vCenter lock.")
        try:
            vc = xenrt.TEC().lookup("VCENTER")
            s = xenrt.lib.generic.StaticOS(vc['DISTRO'], vc['ADDRESS'])
            s.os.enablePowerShellUnrestricted()
            s.os.ensurePackageInstalled("PowerShell 3.0")
            s.os.sendRecursive("%s/data/tests/vmware" % xenrt.TEC().lookup("XENRT_BASE"), "c:\\vmware")
            xenrt.TEC().logverbose(s.os.execCmd("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\addhost.ps1 %s %s %s %s %s %s %s %s" % (
                                vc['ADDRESS'],
                                vc['USERNAME'],
                                vc['PASSWORD'],
                                dc,
                                cluster,
                                self.getIP(),
                                "root",
                                self.password), returndata=True))
        finally:
            lock.release()

