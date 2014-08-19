#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a kvm host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, urllib, os.path

import xenrt
import xenrt.lib.cloud

__all__ = ["createHost",
           "KVMHost"]

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

    if productVersion:
        distro = productVersion
        dd = distro.rsplit('-', 1)
        if len(dd) == 2 and dd[1] == "x64":
            distro = dd[0]
            arch = "x86-64"
        else:
            arch = "x86-32"
    else:
        distro = "centos64"
        arch = "x86-32"

    host = KVMHost(m, productVersion=productVersion, productType=productType)
    extrapackages = []
    extrapackages.append("libvirt")
    rhel7 = False
    if re.search(r"rhel7", distro) or re.search(r"centos7", distro) or re.search(r"oel7", distro):
        rhel7 = True
        extrapackages.append("ntp")
        extrapackages.append("wget")
    else:
        extrapackages.append("python-virtinst")
        extrapackages.append("kvm")
    extrapackages.append("bridge-utils")
    host.installLinuxVendor(distro, arch=arch, extrapackages=extrapackages, options={"ossvg":True})
    host.checkVersion()

    host.execdom0("sed -i 's/\\#listen_tcp = 1/listen_tcp = 1/' /etc/libvirt/libvirtd.conf")
    host.execdom0("sed -i 's/\\#listen_tls = 0/listen_tls = 0/' /etc/libvirt/libvirtd.conf")
    host.execdom0("sed -i 's/\\#auth_tcp = \"sasl\"/auth_tcp = \"none\"/' /etc/libvirt/libvirtd.conf")
    host.execdom0("sed -i 's/\\#LIBVIRTD_ARGS=\"--listen\"/LIBVIRTD_ARGS=\"--listen\"/' /etc/sysconfig/libvirtd")
    host.execdom0("service libvirtd restart")
    try:
        host.execdom0("service firewalld stop")
    except:
        host.execdom0("service iptables stop")

    if rhel7:
        # NetworkManager doesn't support bridging and must be disabled
        host.execdom0("chkconfig NetworkManager off")
        host.execdom0("chkconfig network on")
        host.execdom0("service NetworkManager stop")

    host.virConn = host._openVirConn()

    host.execvirt("virsh net-destroy default")
    host.execvirt("virsh net-undefine default")
    host.createNetwork("cloudbr0")

    networkConfig  = "<network>"
    networkConfig += "<name>cloudbr0</name>"
    networkConfig += "<forward mode='bridge'/>"
    networkConfig += "<bridge name='cloudbr0'/>"
    networkConfig += "</network>"
    host.execvirt("virsh net-define /dev/stdin <<< \"%s\"" % (networkConfig, ))

    # Sometimes the networking changes can break our virConn, needed for the
    # SR creation step. As a quick fix lets just reestablish it and let the old
    # one be GC'd
    # TODO: Optimise the libvirt support so this is automatic
    host.virConn = host._openVirConn()

    # Create local storage with type EXT
    if installSRType != "no":
        host.execdom0("lvcreate VGXenRT -l 100%FREE --name lv_storage")
        sr = xenrt.lib.kvm.EXTStorageRepository(host, "LocalStorage")
        sr.createOn("/dev/VGXenRT/lv_storage")
        host.addSR(sr, default=True)

    # SELinux support for NFS SRs on KVM (eg. for ISO files)
    # https://bugzilla.redhat.com/show_bug.cgi?id=589922
    try:
        host.execdom0("getsebool virt_use_nfs")
        host.execdom0("setsebool virt_use_nfs on")
    except:
        # In RHEL7 these commands throw an exception if SELinux is disabled.
        pass

    if cpufreqgovernor:
        output = host.execcmd("head /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor || true")
        xenrt.TEC().logverbose("Before changing cpufreq governor: %s" % (output,))

        # For each CPU, set the scaling_governor. This command will fail if the host does not support cpufreq scaling (e.g. BIOS power regulator is not in OS control mode)
        host.execcmd("for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo %s > $cpu; done" % (cpufreqgovernor,))

        output = host.execcmd("head /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor || true")
        xenrt.TEC().logverbose("After changing cpufreq governor: %s" % (output,))

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    return host

class KVMHost(xenrt.lib.libvirt.Host):

    LIBVIRT_REMOTE_DAEMON = True

    default_eth = "eth0"

    def __init__(self, machine, productVersion="kvm", productType="kvm"):
        xenrt.lib.libvirt.Host.__init__(self, machine,
                             productType=productType,
                             productVersion=productVersion)

    def _getVirURL(self):
        return "qemu+tcp://%s/system" % (self.getIP(), )

    def guestFactory(self):
        return xenrt.lib.kvm.KVMGuest

    def lookupDefaultSR(self):
        # TODO
        return self.srs[self.defaultsr].uuid

    def getSRNameFromPath(self, srpath):
        """Returns the name of the SR in the path.
        srpath can be the SR mountpoint, or a volume within the mountpoint.
        Returns None if the path is not one of the above."""
        r = re.match(r"/var/run/sr-mount/([^/]*)", srpath)
        if r:
            return urllib.unquote(r.group(1))
        else:
            return None

    def getSRPathFromName(self, srname):
        return "/var/run/sr-mount/%s" % (urllib.quote(srname), )

    def getBridge(self, eth):
        return eth.replace("eth","cloudbr")

    def getPrimaryBridge(self):
        return self.getBridge(self.getDefaultInterface())

    def createNetwork(self, name="bridge"):
        self.execvirt("virsh iface-bridge %s %s --no-stp 10" % (self.getDefaultInterface(), name))

    def removeNetwork(self, bridge=None, nwuuid=None):
        if bridge:
            self.execvirt("virsh iface-unbridge %s" % (bridge, ))

    def checkVersion(self):
        self.productVersion = "kvm"
        self.productRevision = self.execdom0("uname -r | cut -d'-' -f1")

    def getDefaultInterface(self):
        """Return the device for the configured default interface."""
        mac = self.lookup("MAC_ADDRESS", None)
        if mac:
            try:
                ifdata = self.execdom0("for i in `ls /sys/class/net`; do echo -n \"${i} \"; cat /sys/class/net/${i}/address; done")
                for l in ifdata.splitlines():
                    ls = l.split()
                    if not ls[0].startswith("eth"): # TODO: This may not work in general, as later Linux releases are stopping using eth prefixes!
                        continue # Ignore any existing bridge devices
                    if ls[1].lower() == mac.lower():
                        return ls[0]
                
                raise xenrt.XRTFailure("Could not find an interface for %s" % (mac))
            except Exception, e:
                xenrt.TEC().warning("Exception looking up default interface: "
                                    "%s" % (str(e)))
        # Otherwise fall back to the default
        return self.default_eth

    def createNetworkTopology(self, topology):
        """Create the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        if not physList:
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        # configure single nic non vlan jumbo networks
        requiresReboot = False
        has_new_ip = False
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            xenrt.TEC().logverbose("Processing p=%s" % (p,))
            # create only on single nic non valn nets
            if len(nicList) == 1  and len(vlanList) == 0:
                eth = nicList[0]
                previous_eth = self.default_eth
                previous_bridge = self.getBridge(previous_eth)
                xenrt.TEC().logverbose("Processing eth%s: %s" % (eth, p))
                #make sure it is up
                self.execcmd("ifup eth%s || true" % eth)

                #set up new primary kvm bridge if necessary
                pri_eth = "eth%s" % (eth,)
                pri_bridge = self.getBridge(pri_eth)
                has_virsh_pri_bridge = self.execcmd("virsh iface-list|grep %s|wc -l" % (pri_bridge,)).strip() != "0"
                if not has_virsh_pri_bridge:
                    self.createNetwork(name=pri_bridge)
                    host.execvirt("virsh net-destroy %s" % (previous_bridge,))
                    host.execvirt("virsh net-undefine %s" % (previous_bridge,))
                    networkConfig  = "<network>"
                    networkConfig += "<name>%s</name>" % (pri_bridge,)
                    networkConfig += "<forward mode='bridge'/>"
                    networkConfig += "<bridge name='%s'/>" % (pri_bridge,)
                    networkConfig += "</network>"
                    host.execvirt("virsh net-define /dev/stdin <<< \"%s\"" % (networkConfig, ))

                if mgmt:
                    #use the ip of the mgtm nic on the list as the default ip of the host
                    mode = mgmt
                    if mode == "static":
                        newip, netmask, gateway = self.getNICAllocatedIPAddress(eth)
                        xenrt.TEC().logverbose("XenRT static configuration for host %s: ip=%s, netmask=%s, gateway=%s" % (self, ip, netmask, gateway))
                        #TODO: set also BOOTPROTO,IPADDR,NETMASK in network-scripts/ifcfg-eth
                        self.execcmd("ifconfig %s %s netmask %s" % (pri_bridge, newip, netmask))

                    elif mode == "dhcp":
                        #TODO: set also BOOTPROTO=dhcp in network-scripts/ifcfg-eth
                        pass

                    #read final ip in eth
                    newip = self.execcmd("ip addr show %s|grep \"inet \"|gawk '{print $2}'| gawk -F/ '{print $1}'" % (pri_bridge,)).strip()
                    if newip and len(newip)>0:
                        xenrt.TEC().logverbose("New IP %s for host %s on %s" % (newip, self, pri_bridge))
                        self.machine.ipaddr = newip
                        has_new_ip = True
                        self.default_eth = pri_eth
                        xenrt.TEC().logverbose("New virsh default network: %s" % self.default_eth)
                    else:
                        raise xenrt.XRTError("Wrong new IP %s for host %s on %s" % (newip, self, pri_bridge))

                if jumbo == True:
                    #enable jumbo frames immediately
                    self.execcmd("ifconfig %s mtu 9000" % (pri_eth,))
                    #make it permanent
                    self.execcmd("sed -i 's/MTU=.*$/MTU=\"9000\"/; t; s/^/MTU=\"9000\"/' /etc/sysconfig/network-scripts/ifcfg-%s" % (pri_eth,))
                    requiresReboot = False
                elif jumbo != False: #ie jumbo is a string
                    self.execcmd("ifconfig %s mtu %s" % (pri_eth, jumbo))
                    self.execcmd("sed -i 's/MTU=.*$/MTU=\"%s\"/; t; s/^/MTU=\"%s\"/' /etc/sysconfig/network-scripts/ifcfg-%s" % (jumbo,jumbo,pri_eth))
                    requiresReboot = False

            if len(nicList) > 1:
                raise xenrt.XRTError("Can't create bond on %s using %s" %
                                       (network, str(nicList)))
            if len(vlanList) > 0:
                raise xenrt.XRTError("Can't create vlan on %s using %s" %
                                       (network, str(vlanList)))

        if len(physList)>0:
            if not has_new_ip:
                raise xenrt.XRTError("The network topology did not define a management IP for the host")

        # Only reboot if required and once while physlist is processed
        if requiresReboot == True:
            self.reboot()

        # Make sure no firewall will interfere with tests
        self.execcmd("iptables -F")

    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""
        pass

    def tailorForCloudStack(self, isCCP, isLXC=False):
        """Tailor this host for use with ACS/CCP"""

        # Check that we haven't already tailored the host
        if self.execdom0("ls /var/lib/xenrt/cloudTailored", retval="code") == 0:
            return

        # Common operations
        # hostname --fqdn must give a response
        self.execdom0("echo '%s %s.%s %s' >> /etc/hosts" %
                      (self.getIP(),
                       self.getName(),
                       self.lookup("DNS_DOMAIN", "xenrt"),
                       self.getName()))

        # Start NTP
        self.execdom0("service ntpd start")
        self.execdom0("chkconfig ntpd on")

        # Set up a yum repository so we can actually install packages
        self.updateYumConfig(self.distro, self.arch)

        self.addExtraLogFile("/var/log/cloudstack")

        if isCCP:
            # Citrix CloudPlatform specific operations

            self.execdom0("yum erase -y qemu-kvm")
            # Install CloudPlatform packages
            cloudInputDir = xenrt.TEC().lookup("CLOUDINPUTDIR", None)
            if not cloudInputDir:
                raise xenrt.XRTError("No CLOUDINPUTDIR specified")
            xenrt.TEC().logverbose("Downloading %s" % cloudInputDir)
            ccpTar = xenrt.TEC().getFile(cloudInputDir)
            xenrt.TEC().logverbose("Got %s" % ccpTar)
            webdir = xenrt.WebDirectory()
            webdir.copyIn(ccpTar)
            ccpUrl = webdir.getURL(os.path.basename(ccpTar))
            self.execdom0('wget %s -O /tmp/cp.tar.gz' % (ccpUrl))
            webdir.remove()
            self.installJSVC()
            self.execdom0("cd /tmp && mkdir cloudplatform && tar -xvzf cp.tar.gz -C /tmp/cloudplatform")
            installDir = os.path.dirname(self.execdom0('find /tmp/cloudplatform/ -type f -name install.sh'))
            result = self.execdom0("cd %s && ./install.sh -a" % (installDir))
            # CS-20675 - install.sh can exit with 0 even if the install fails!
            if "You could try using --skip-broken to work around the problem" in result:
                raise xenrt.XRTError("Dependency failure installing CloudPlatform")

            # NFS services
            self.execdom0("service rpcbind start")
            self.execdom0("service nfs start")
            self.execdom0("chkconfig rpcbind on")
            try:
                self.execdom0("chkconfig nfs on")
            except:
                self.execdom0("systemctl enable nfs-server.service") # RHEL7
        else:
            # Apache CloudStack specific operations

            # Install cloudstack-agent
            self.installJSVC()
            self.execdom0("yum install -y ipset jna")
            artifactDir = xenrt.lib.cloud.getLatestArtifactsFromJenkins(self, ["cloudstack-common-", "cloudstack-agent-"])
            self.execdom0("rpm -ivh %s/cloudstack-*.rpm" % artifactDir)

            # Modify /etc/libvirt/qemu.conf
            self.execdom0("sed -i 's/\\# vnc_listen = \"0.0.0.0\"/vnc_listen = \"0.0.0.0\"/' /etc/libvirt/qemu.conf")
            self.execdom0("service libvirtd restart")

            # Ensure SELinux is in permissive mode
            self.execdom0("sed -i 's/SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config")
            self.execdom0("/usr/sbin/setenforce permissive")

        # Set up /etc/cloudstack/agent/agent.properties
        self.execdom0("echo 'public.network.device=cloudbr0' >> /etc/cloudstack/agent/agent.properties")
        self.execdom0("echo 'private.network.device=cloudbr0' >> /etc/cloudstack/agent/agent.properties")

        # Write the stamp file to record this has already been done
        self.execdom0("mkdir -p /var/lib/xenrt")
        self.execdom0("touch /var/lib/xenrt/cloudTailored")

    def installJSVC(self):
        self.execdom0("yum install -y java-1.6.0 java*1.7* jakarta-commons-daemon")
        # (we need java-1.6.0 as the package has a dependency on it, but it actually fails unless you run
        #  java-1.7.0, so we need to update-alternatives to use it - GRR!)
        if not '1.7.0' in self.execdom0('java -version').strip():
                javaDir = self.execdom0('update-alternatives --display java | grep "^/usr/lib.*1.7.0"').strip()
                self.execdom0('update-alternatives --set java %s' % (javaDir.split()[0]))
        if re.search(r"rhel7", self.distro) or re.search(r"centos7", self.distro) or re.search(r"oel7", self.distro):
            # RHEL7 based systems don't have jakarta-commons-daemon
            return
        # TODO: Don't hardcode the jsvc URL
        jsvc = xenrt.TEC().getFile("/usr/groups/xenrt/cloud/jakarta-commons-daemon-jsvc-1.0.1-8.9.el6.x86_64.rpm")
        webdir = xenrt.WebDirectory()
        webdir.copyIn(jsvc)
        jsvcUrl = webdir.getURL("jakarta-commons-daemon-jsvc-1.0.1-8.9.el6.x86_64.rpm")
        self.execdom0("wget %s -O /tmp/jakarta-commons-daemon-jsvc-1.0.1-8.9.el6.x86_64.rpm" % jsvcUrl)
        webdir.remove()
        self.execdom0("rpm -ivh /tmp/jakarta-commons-daemon-jsvc-1.0.1-8.9.el6.x86_64.rpm")

