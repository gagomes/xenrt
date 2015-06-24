#
# XenRT: Test harness for Xen and the XenServer product family
#
# OSS Xen host library
#
# Copyright (c) 2014 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, re, json
import xenrt

# Symbols we want to export from the package.
__all__ = ["OSSHost",
           "createHost",
           "hostFactory"]

def hostFactory(hosttype):
    return xenrt.lib.oss.OSSHost

def createHost(id=0,
               version=None,
               pool=None,
               name=None,
               dhcp=True,
               license=True,
               diskid=0,
               diskCount=1,
               productVersion=None,
               productType=None,
               withisos=True,
               noisos=None,
               overlay=None,
               installSRType=None,
               suppackcds=None,
               addToLogCollectionList=False,
               disablefw=False,
               cpufreqgovernor=None,
               defaultlicense=True,
               ipv6=None,
               enableAllPorts=True,
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
    mname = xenrt.TEC().lookup(machine)
    m = xenrt.PhysicalHost(mname)

    xenrt.GEC().startLogger(m)

    host = xenrt.lib.oss.OSSHost(m, version)
    host.installLinuxVendor("debian70", arch="x86-64")

    host.installXen()
    if withisos:
        host.setupISOMounts()

    if cpufreqgovernor:
        output = host.execcmd("head /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor || true")
        xenrt.TEC().logverbose("Before changing cpufreq governor: %s" % (output,))

        # For each CPU, set the scaling_governor. This command will fail if the host does not support cpufreq scaling (e.g. BIOS power regulator is not in OS control mode)
        # TODO also make this persist across reboots
        host.execcmd("for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo %s > $cpu; done" % (cpufreqgovernor,))

        output = host.execcmd("head /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor || true")
        xenrt.TEC().logverbose("After changing cpufreq governor: %s" % (output,))

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    return host

class OSSHost(xenrt.lib.native.NativeLinuxHost):

    def __init__(self, machine, productVersion=None):
        xenrt.lib.native.NativeLinuxHost.__init__(self, machine)
        self.pddomaintype = "OSS"
        self.xenInstalled = False

    def existing(self):
        xenrt.lib.native.NativeLinuxHost.existing(self)
        # See if we have Xen installed
        if self.execdom0("dmesg | grep 'Xen version:'", retval="code") == 0:
            self.xenInstalled = True

        self.check()

    def installXen(self):
        # First install dependencies
        self.execdom0("apt-get install -y libyajl2 libglib2.0-0 libssh2-1 libcurl3 libpng12-0 libjpeg8 libsdl1.2debian libaio1 libpixman-1-0 bridge-utils tcpdump")
        
        # Find and install the .deb
        webdir = xenrt.WebDirectory()
        xendeb = xenrt.TEC().getFile("xen.deb")
        if not xendeb:
            raise xenrt.XRTError("Unable to find Xen deb package")

        webdir.copyIn(xendeb, "xen.deb")
        self.execdom0("wget -q -O /tmp/xen.deb %s" % (webdir.getURL("xen.deb")))
        self.execdom0("dpkg -i /tmp/xen.deb")

        # Update libraries
        self.execdom0("/sbin/ldconfig")

        # Sort out grub
        self.execdom0("sed -i 's/GRUB_DEFAULT=0/GRUB_DEFAULT=2/' /etc/default/grub")
        self.execdom0("/usr/sbin/update-grub")

        # Enable Xen services
        self.execdom0("/usr/sbin/update-rc.d xencommons defaults")

        # Prepare the network config
        self.execdom0("sed -i 's/iface eth0 inet dhcp/iface eth0 inet manual/' /etc/network/interfaces")
        self.execdom0("sed -i 's/iface eth0 inet6 auto/iface eth0 inet6 manual/' /etc/network/interfaces")
        self.execdom0("echo 'auto xenbr0\niface xenbr0 inet dhcp\n  bridge_ports eth0\n' >> /etc/network/interfaces")

        # Create a directory to store VM disks in
        self.execdom0("mkdir -p /data")        

        # Reboot
        self.reboot()

        self.xenInstalled = True

        # Check we have a working Xen installation
        self.check()

    def setupISOMounts(self):
        isoMounts = {'isos': self.lookup("EXPORT_ISO_NFS")}
        staticIsos = self.lookup("EXPORT_ISO_NFS_STATIC", None)
        if staticIsos:
            isoMounts['isos-static'] = staticIsos
        for i in isoMounts:
            self.execSSH("mkdir -p /mnt/%s" % i)
            self.execSSH("echo '%s /mnt/%s nfs ro 0 0' >> /etc/fstab" % (isoMounts[i], i))
            self.execSSH("mount /mnt/%s" % i)

    def check(self):
        # TODO: Improve this to be more thorough than just checking an xl command responds!
        self.execdom0("xl list")

    def arpwatch(self, iface, mac, timeout):
        """Monitor an interface (or bridge) for an ARP reply"""

        if xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True):
            xenrt.lib.native.NativeLinuxHost.arpwatch(self, iface, mac, timeout)

        xenrt.TEC().logverbose("Sniffing ARPs on %s for %s" % (iface, mac))

        deadline = xenrt.util.timenow() + timeout

        myres = []
        myres.append(re.compile(r"(?P<ip>[0-9.]+) is-at (?P<mac>[0-9a-f:]+)"))
        myres.append(re.compile(r"> (?P<mac>[0-9a-f:]+).*> (?P<ip>[0-9.]+).bootpc: BOOTP/DHCP, Reply"))
        myres.append(re.compile(r"\s+(?P<mac>[0-9a-f:]+)\s+>\s+Broadcast.*ARP.*tell\s+(?P<ip>[0-9.]+)"))
        myres.append(re.compile(r"\s+(?P<mac>[0-9a-f:]+)\s+>\s+ff:ff:ff:ff:ff:ff.*ARP.*tell\s+(?P<ip>[0-9.]+)")) # tcpdump-uw formatting of 'broadcast' MAC
        myres.append(re.compile(r"> (?P<mac>[0-9a-f:]+),.* [0-9.]+ > (?P<ip>[0-9.]+)\.[0-9]+: BOOTP/DHCP"))
        ip = None
        lip = None
        while True:
            tcpdump_command = "%s -lne -i \"%s\" arp or udp port bootps" % \
                              (self.TCPDUMP, iface)
            # Start a tcpdump
            s = xenrt.ssh.SSHCommand(self.machine.ipaddr,
                                     tcpdump_command,
                                     username="root",
                                     timeout=3600,
                                     level=xenrt.RC_ERROR,
                                     password=self.password)
            xenrt.TEC().logverbose("Command: %s" % tcpdump_command)

            try:
                # Watch the output for our MAC
                while True:
                    now = xenrt.util.timenow()
                    if now > deadline:
                        ip = self.checkLeases(mac)
                        if not ip and lip:
                            ip = lip
                        if ip:
                            break
                        return None

                    output = s.fh.readline()
                    if len(output) == 0:
                        break
                    for myre in myres:
                        r = myre.search(output)
                        if r:
                            tip = r.group("ip")
                            tmac = r.group("mac")
                            if xenrt.util.normaliseMAC(tmac) == xenrt.util.normaliseMAC(mac) and not tip in ("255.255.255.255", "0.0.0.0"):
                                ip = tip
                                xenrt.TEC().logverbose("Matched: %s" % (output))
                                break
                    if ip:
                        if re.match("169\.254\..*", ip):
                            lip = ip
                            ip = None
                        else:
                            break

            finally:
                s.client.close()
                s.close()

            if ip:
                break
            xenrt.sleep(2)

        if re.match("169\.254\..*", ip):
            raise xenrt.XRTFailure("VM gave itself a link-local address.")

        return ip

    def _xl(self, command, args=[], level=xenrt.RC_FAIL, nolog=False):
        cmd = "xl %s %s" % (command, string.join(args))
        return self.execSSH(cmd, level=level, nolog=nolog)

    def _list(self):
        """Returns the JSON interpreted output of xl list -l"""
        # TODO: Handle parsing errors properly
        data = self._xl("list", ["-l"])
        return json.loads(data) 

    def _writeXLConfig(self, xlcfg):
        tmpfile = self.execSSH("mktemp").strip()
        localtmp = xenrt.TEC().tempFile()
        f = file(localtmp, "w")
        f.write(xlcfg)
        f.close()
        self.sftpClient().copyTo(localtmp, tmpfile)
        return tmpfile

    def createInstance(self, xlcfg, uuid):
        """Creates an instance, returning the domid"""
        tmpfile = self._writeXLConfig(xlcfg)
        try:
            self._xl("create", [tmpfile])
        finally:
            if not xenrt.TEC().lookup("OPTION_KEEP_XLCFGS", False, boolean=True):
                self.execSSH("rm -f %s" % (tmpfile), level=xenrt.RC_OK)
        # xl create doesn't return the domid, so we need to look this up
        data = self._list()
        for dom in data:
            if dom['config']['c_info']['uuid'] == uuid:
                return dom['domid']
        raise xenrt.XRTError("domid not found after creating domain")

    def destroyInstance(self, domid):
        """Destroys the given domid"""
        self._xl("destroy", [str(domid)])

    def shutdownInstance(self, domid):
        """Shuts down the given domid"""
        self._xl("shutdown", [str(domid)])

    def rebootInstance(self, domid):
        """Reboots the given domid"""
        self._xl("reboot", [str(domid)])

    def saveInstance(self, domid, saveFile):
        """Suspends the given domid into the specified save file"""
        self._xl("save", [str(domid), saveFile])

    def restoreInstance(self, saveFile):
        """Restores the given save file"""
        self._xl("restore", [saveFile])

    def authoriseSSHKey(self, publicKey):
        """Authorises the given public Key for SSH access"""
        # Check if it's already present
        if self.execSSH("grep '%s' /root/.ssh/authorized_keys" % publicKey, retval="code") != 0:
            self.execSSH("echo '%s' >> /root/.ssh/authorized_keys" % publicKey)

    def migrateInstance(self, domid, to):
        """Migrates the given domid to the specified host"""
        if not isinstance(to, OSSHost):
            raise xenrt.XRTError("Cannot migrate to this type of host")

        # Set up SSH keys needed for the migration
        if self.execSSH("ls -l /root/.ssh/id_rsa.pub", retval="code") != 0:
            self.execSSH("ssh-keygen -f /root/.ssh/id_rsa -P ''")
        publicKey = self.execSSH("cat /root/.ssh/id_rsa.pub").strip()
        to.authoriseSSHKey(publicKey)

        self._xl("migrate", [domid, to.getIP()])

    def execSSH(self, *args, **kwargs):
        return self.execdom0(*args, **kwargs)

    def updateConfig(self, domid, xlcfg):
        """Updates the configuration for the given domid"""
        tmpfile = self._writeXLConfig(xlcfg)
        try:
            self._xl("config-update", [str(domid), tmpfile])
        finally:
            self.execSSH("rm -f %s" % (tmpfile), level=xenrt.RC_OK)

    def listGuests(self):
        """Returns a list of guest UUIDs running on this host"""
        data = self._list()
        guests = []
        for dom in data:
            guests.append(dom['config']['c_info']['uuid'])
        return guests

    def listGuestsData(self):
        """Returns a dictionary keyed by UUID"""
        data = self._list()
        guests = {}
        for dom in data:
            guests[dom['config']['c_info']['uuid']] = (dom['domid'], self.getState(dom['domid']))
        return guests

    def getState(self, domid):
        """Returns the state of the specified domid"""
        data = self._xl("list", [str(domid)])
        lines = data.splitlines()
        ls = lines[-1].split()
        state = ls[4]
        return state.replace("-","")

