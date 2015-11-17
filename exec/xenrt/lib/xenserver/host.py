#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a XenServer host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#


import sys, string, os.path, glob, time, re, math, random, shutil, os, stat, datetime
import traceback, threading, types, collections
import xml.dom.minidom
import tarfile
import IPy
import ssl
import xenrt
import xenrt.lib.xenserver
import xenrt.lib.xenserver.guest
import xenrt.lib.xenserver.install
import xenrt.lib.xenserver.jobtests
from  xenrt.lib.xenserver import licensedfeatures
import XenAPI
from xenrt.lazylog import *
from xenrt.lib.xenserver.iptablesutil import IpTablesFirewall
from xenrt.lib.xenserver.licensing import LicenseManager, XenServerLicenseFactory
from itertools import imap


# Symbols we want to export from the package.
__all__ = ["Host",
           "MNRHost",
           "BostonHost",
           "BostonXCPHost",
           "TampaHost",
           "TampaXCPHost",
           "DundeeHost",
           "CreedenceHost",
           "ClearwaterHost",
           "Pool",
           "watchForInstallCompletion",
           "createHost",
           "hostFactory",
           "CLI_LEGACY_NATIVE",
           "CLI_LEGACY_COMPAT",
           "CLI_NATIVE",
           "poolFactory",
           "MNRPool",
           "BostonPool",
           "TampaPool",
           "ClearwaterPool",
           "CreedencePool",
           "DundeePool",
           "RollingPoolUpdate",
           "Tile",
           "IOvirt",
           "Appliance"]

CLI_LEGACY_NATIVE = 1   # Old style CLI on an old-style host
CLI_LEGACY_COMPAT = 2   # Old style CLI on a new host
CLI_NATIVE = 3          # New style CLI

TEMPLATE_SR_UUID = "9ab6d700-7b6f-4d2f-831f-e7d5330b4534"

def hostFactory(hosttype):
    if hosttype == "Dundee":
        return xenrt.lib.xenserver.DundeeHost
    elif hosttype in ("Creedence", "Cream"):
        return xenrt.lib.xenserver.CreedenceHost
    elif hosttype in ("Clearwater"):
        return xenrt.lib.xenserver.ClearwaterHost
    elif hosttype in ("Tampa", "Tallahassee"):
        return xenrt.lib.xenserver.TampaHost
    elif hosttype == "TampaXCP":
        return xenrt.lib.xenserver.TampaXCPHost
    elif hosttype in ("Boston", "Sanibel", "SanibelCC"):
        return xenrt.lib.xenserver.BostonHost
    elif hosttype == "BostonXCP":
        return xenrt.lib.xenserver.BostonXCPHost
    elif hosttype in ("MNR", "MNRCC", "Cowley", "Oxford"):
        return xenrt.lib.xenserver.MNRHost
    return xenrt.lib.xenserver.Host


def poolFactory(mastertype):
    if mastertype in ("Dundee"):
        return xenrt.lib.xenserver.DundeePool
    elif mastertype in ("Creedence", "Cream"):
        return xenrt.lib.xenserver.CreedencePool
    elif mastertype in ("Clearwater"):
        return xenrt.lib.xenserver.ClearwaterPool
    elif mastertype in ("Boston", "BostonXCP", "Sanibel", "SanibelCC", "Tampa", "TampaXCP", "Tallahassee"):
        return xenrt.lib.xenserver.BostonPool
    elif mastertype in ("MNR", "Cowley", "Oxford"):
        return xenrt.lib.xenserver.MNRPool
    return xenrt.lib.xenserver.Pool


def logInstallEvent(func):
    def getHostName(*args, **kwargs):
        try:
            hostid = 0
            if kwargs.has_key('id'):
                hostid = kwargs['id']
            elif len(args) > 0:
                hostid = args[0]
            if kwargs.get('containerHost') != None:
                # We don't want to log virtual hosts
                return None
            return xenrt.TEC().lookup("RESOURCE_HOST_%s" % (hostid), None)
        except Exception, e:
            xenrt.TEC().logverbose("Exception getting host name to log in events - %s" % str(e))
            return None

    def wrapper(*args, **kwargs):
        hostname = getHostName(*args, **kwargs)
        try:
            ret = func(*args, **kwargs)
            if hostname:
                try:
                    xenrt.GEC().dbconnect.jobctrl("event", ["XSInstallSucceeded", hostname, str(xenrt.GEC().jobid())])
                except Exception, e:
                    xenrt.TEC().logverbose("Exception logging successful install - %s" % str(e))
            return ret
        except:
            if hostname:
                try:
                    xenrt.GEC().dbconnect.jobctrl("event", ["XSInstallFailed", hostname, str(xenrt.GEC().jobid())])
                except Exception, e:
                    xenrt.TEC().logverbose("Exception logging successful install - %s" % str(e))
            raise
    return wrapper

def productVersionFromInputDir(inputDir):
    fn = xenrt.TEC().getFile("%s/xe-phase-1/globals" % inputDir, "%s/globals" % inputDir)
    if fn:
        for line in open(fn).xreadlines():
            match = re.match('^PRODUCT_VERSION="(.+)"', line)
            if match:
                hosttype = xenrt.TEC().lookup(["PRODUCT_CODENAMES", match.group(1)], None)
                if hosttype:
                    return hosttype
    return xenrt.TEC().lookup("PRODUCT_VERSION", None)

@logInstallEvent
def createHost(id=0,
               version=None,
               pool=None,
               name=None,
               dhcp=True,
               license=True,
               diskCount=1,
               productType=None,
               productVersion=None,
               withisos=False,
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
               iScsiBootLun=None,
               iScsiBootNets=[],
               extraConfig=None,
               containerHost=None,
               vHostName=None,
               vHostCpus=2,
               vHostMemory=4096,
               vHostDiskSize=50,
               vHostSR=None,
               vNetworks=None,
               iommu=False,
               installnetwork=None,
               **kwargs):

    # noisos isn't used here, it is present in the arg list to
    # allow its use as a flag in PrepareNode in sequence.py

    if containerHost != None:
        container = xenrt.GEC().registry.hostGet("RESOURCE_HOST_%d" % containerHost)
        machine = container.createNestedHost(name=vHostName, cpus=vHostCpus, memory=vHostMemory, diskSize=vHostDiskSize, sr=vHostSR, networks=vNetworks)
    else:
        machine = str("RESOURCE_HOST_%s" % (id))
    
    if productVersion and not version:
        # If we've asked for a named product version but not provided
        # an input directory for it then look one up in the config
        version = productInputdirForVersion(productVersion)
    if version:
        xenrt.TEC().setInputDir(version)
    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    runOverdueCleanup(m.name)
    xenrt.GEC().startLogger(m)
    if productVersion:
        hosttype = productVersion
    else:
        hosttype = productVersionFromInputDir(xenrt.TEC().getInputDir())

    host = xenrt.lib.xenserver.hostFactory(hosttype)(m,
                                                     productVersion=hosttype)

    if iScsiBootLun:
        host.bootLun = iScsiBootLun
        if len(iScsiBootNets) > 0:
            host.bootNics = [host.listSecondaryNICs(x)[0] for x in iScsiBootNets]
        else:
            host.bootNics = [host.listSecondaryNICs("NPRI")[0]]
        # If we're multipathed, we'll need to create the local SR after installation, if not then the installer can set it up for us
        if len(iScsiBootNets) > 1:
            xenrt.TEC().config.setVariable(["HOST_CONFIGS",host.getName(),"OPTION_ROOT_MPATH"],"enabled")
            xenrt.TEC().config.setVariable(["HOST_CONFIGS",host.getName(),"LOCAL_SR_POST_INSTALL"],"yes")
        else:
            xenrt.TEC().config.setVariable(["HOST_CONFIGS",host.getName(),"OPTION_ROOT_MPATH"],"")
            xenrt.TEC().config.setVariable(["HOST_CONFIGS",host.getName(),"LOCAL_SR_POST_INSTALL"],"no")

    if enableAllPorts:
        host.enableAllNetPorts()

    if addToLogCollectionList and xenrt.TEC().tc:
        xenrt.TEC().tc.getLogsFrom(host)
    nameserver = None
    hostname = None
    ipv6_addr = None
    gateway6 = None
    interfaces = []

    if host.lookup("HOST_STATIC_IP", False, boolean=True):
        dhcp = False

    if noipv4:
        # We should atleast have an ipv6 address
        if ipv6 not in set(["static", "dhcp", "autoconf"]):
            raise xenrt.XRTError("No IPv4/IPv6 address (dhcp/static) specified")
        if ipv6 == "static":
            ipv6_addr = host.lookup("HOST_ADDRESS6")
            gateway6 = host.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY6"])
        if ipv6 in set(["static", "autoconf"]):
            n = host.lookup(["NETWORK_CONFIG", "DEFAULT", "NAMESERVERS"], None)
            if n:
                nameserver = string.split(n, ",")[0]
            else:
                nameserver = None
            hostname = m.name
        interfaces.append((None, "yes", "none", None, None, None, ipv6, ipv6_addr, gateway6))
    else:
        if dhcp:

            if ipv6 == "static":
                ipv6_addr = host.lookup("HOST_ADDRESS6")
                gateway6 = host.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY6"])

            if ipv6 in set(["static", "autoconf"]):
                n = host.lookup(["NETWORK_CONFIG", "DEFAULT", "NAMESERVERS"], None)
                if n:
                    nameserver = string.split(n, ",")[0]
                else:
                    nameserver = None
                    hostname = m.name
                    
            if ipv6 in set(["dhcp", "autoconf", "none", "static"]):
                interfaces.append((None, "yes", "dhcp", None, None, None, ipv6, ipv6_addr, gateway6))
            else:
                interfaces.append((None, "yes", "dhcp", None, None, None, None, None, None))
        else:
            ip = m.ipaddr
            netmask = host.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"])
            gateway = host.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY"])

            if ipv6 == "static":
                ipv6_addr = host.lookup("HOST_ADDRESS6")
                gateway6 = host.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY6"])

            if ipv6 in set(["dhcp", "autoconf", "none", "static"]):
                interfaces.append((None, "yes", "static", ip, netmask, gateway, ipv6, ipv6_addr, gateway6))
            else:
                interfaces.append((None, "yes", "static", ip, netmask, gateway, None, None, None))
    
            n = host.lookup(["NETWORK_CONFIG", "DEFAULT", "NAMESERVERS"], None)
            #CHECKME: Do we need ipv6 nameservers ??? (DNS64 maybe)
            if n:
                nameserver = string.split(n, ",")[0]
            else:
                nameserver = None
            hostname = m.name

    guestdisks = host.getGuestDisks(ccissIfAvailable=host.USE_CCISS, count=diskCount, legacySATA=(not host.isCentOS7Dom0()))

    if diskCount > len(guestdisks):
        raise xenrt.XRTError("Wanted %u disks but we only have: %s" %
                             (diskCount, string.join(guestdisks)))
    if host.bootLun:
        primarydisk = "disk/by-id/scsi-%s" % host.bootLun.getID()
    else:
        primarydisk = host.getInstallDisk(ccissIfAvailable=host.USE_CCISS, legacySATA=(not host.isCentOS7Dom0()))

    handle = host.install(interfaces=interfaces,
                          nameserver=nameserver,
                          primarydisk=primarydisk,
                          guestdisks=guestdisks,
                          overlay=overlay,
                          installSRType=installSRType,
                          hostname=hostname,
                          suppackcds=suppackcds,
                          installnetwork=installnetwork)

    if license:
        if not defaultlicense:
            guest = xenrt.TEC().registry.guestGet("LICENSE_SERVER")
            licenseServer = None
            if guest:
                licenseServer = guest.getV6LicenseServer(useEarlyRelease=False, install=False)
            else:
                guest = xenrt.GenericGuest(xenrt.TEC().lookup("EXTERNAL_LICENSE_SERVER"))
                guest.mainip = xenrt.TEC().lookup("EXTERNAL_LICENSE_SERVER")
                guest.windows = True
                xenrt.TEC().registry.guestPut("LICENSE_SERVER", guest)
                licenseServer = guest.getV6LicenseServer(useEarlyRelease=False, install=False)
            host.license(edition=license, v6server=licenseServer)
        elif type(license) == type(""):
            host.license(sku=license)
        else:
            host.license()

    if disablefw:
        xenrt.TEC().warning("Disabling host firewall")
        host.execdom0("service iptables stop")
        host.execdom0("chkconfig iptables off")

    if cpufreqgovernor:
        output = host.execdom0("xenpm get-cpufreq-para | fgrep -e current_governor -e 'cpu id' || true")
        xenrt.TEC().logverbose("Before changing cpufreq governor: %s" % (output,))

        # Set the scaling_governor. This command will fail if the host does not support cpufreq scaling (e.g. BIOS power regulator is not in OS control mode)
        host.execdom0("xenpm set-scaling-governor %s" % (cpufreqgovernor))

        # Make it persist across reboots
        args = {"cpufreq": "xen:%s" % (cpufreqgovernor)}
        host.setXenCmdLine(set="xen", **args)

        output = host.execdom0("xenpm get-cpufreq-para | fgrep -e current_governor -e 'cpu id' || true")
        xenrt.TEC().logverbose("After changing cpufreq governor: %s" % (output,))

    if iommu:
        xenrt.TEC().logverbose("Enabling IOMMU on host %s..." % (host))
        iovirt = xenrt.lib.xenserver.IOvirt(host)
        iovirt.enableIOMMU(restart_host=False)
        host.enableVirtualFunctions()

    xenrt.TEC().registry.hostPut(machine, host)
    if name:
        xenrt.TEC().registry.hostPut(name, host)

    host.check()
    host.applyWorkarounds()
    host.postInstall()
    papp = False
    
    if not xenrt.TEC().lookup("OPTION_NO_AUTO_PATCH", False, boolean=True):
        papp = host.applyRequiredPatches()

    if withisos:
        srs = []
        srs.append({"name":"XenRT ISOs",
                    "type":"iso",
                    "path":host.lookup("EXPORT_ISO_NFS"),
                    "default":False})
        isos2 = host.lookup("EXPORT_ISO_NFS_STATIC", None)
        if isos2:
            srs.append({"name":"XenRT static ISOs",
                        "type":"iso",
                        "path":isos2,
                        "default":False})
        for s in srs:
            if s["type"] == "iso":
                sr = xenrt.lib.xenserver.ISOStorageRepository(host, s["name"])
                server, path = s["path"].split(":")
                sr.create(server, path)
            host.addSR(sr, default=s["default"])

    if xenrt.TEC().lookup("OPTION_AD_ENABLE", False, boolean=True):
        host.enableDefaultADAuth()

    # Run arbitrary command in dom0 or a script from REMOTE_SCRIPTDIR
    dom0cmd = xenrt.TEC().lookup("DOM0_COMMAND", None)
    if dom0cmd:
        host.execdom0(dom0cmd)

    # Run a script from REMOTE_SCRIPTDIR
    dom0script = xenrt.TEC().lookup("DOM0_SCRIPT", None)
    if dom0script:
        host.execdom0("%s/%s" % (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), dom0script))

    xenrt.TEC().setInputDir(None)

    return host

def productInputdirForVersion(version):
    """Return the product INPUTDIR for the specified version. Beta etc.
    variants are specified by using slash separation, e.g. "George/Beta" """
    inputdir = None
    if xenrt.TEC().lookup("TO_PRODUCT_VERSION" , None) == version.replace("/", ""):
        inputdir = xenrt.TEC().lookup("TO_PRODUCT_INPUTDIR", None)
    elif xenrt.TEC().lookup("FROM_PRODUCT_VERSION" , None) == version.replace("/", ""):
        inputdir = xenrt.TEC().lookup("FROM_PRODUCT_INPUTDIR", None)
    if not inputdir:
        inputdir = xenrt.TEC().lookup("PRODUCT_INPUTDIR_%s" %
                                  (version.replace("/", "").upper()), None)
    if not inputdir:
        inputdir = xenrt.TEC().lookup(\
            "PIDIR_%s" % (version.replace("/", "").upper()), None)
    if not inputdir:
        raise xenrt.XRTError("No product input directory set for %s" %
                             (version))
    return inputdir

def productPatchPathForVersionPatch(version, patchid):
    """Return the path to the specified hotfix for this version."""
    patch = xenrt.TEC().lookup(["CARBON_PATCHES_%s" % (version.upper()),
                                patchid.upper()], None)
    if not patch:
        patch = xenrt.TEC().lookup(["CPATCHES_%s" % (version.upper()),
                                    patchid.upper()], None)
    if not patch:
        raise xenrt.XRTError("No patch path set for for %s %s" %
                             (version, patchid))
    return patch

def createHostViaVersionPath(id=0,
                             pool=None,
                             name=None,
                             dhcp=True,
                             license=True,
                             diskCount=1,
                             versionPath=None,
                             withisos=False,
                             noisos=None,
                             overlay=None,
                             installSRType=None,
                             suppackcds=None,
                             addToLogCollectionList=False,
                             ipv6=None,
                             noipv4=False,
                             basicNetwork=True,
                             extraConfig=None):
    """Install a host and update/upgrade via the specified path."""
    # "Orlando +HF1 +HF2 George"
    # "Miami Orlando George"
    # "Miami +HF1 Floodgate George"
    # "Orlando/Beta George"
    versionPath = versionPath.replace(",", " ")
    versionPathList = versionPath.split()
    currentVersion = versionPathList[0]
    currentMajorVersion = currentVersion.split("/")[0]
    
    # Initial version install
    inputdir = productInputdirForVersion(currentVersion)
    xenrt.TEC().logverbose("createHostViaVersionPath initial install of %s" %
                           (currentVersion))
    host = createHost(id=id,
                      version=inputdir,
                      pool=pool,
                      name=name,
                      dhcp=dhcp,
                      license=license,
                      diskCount=diskCount,
                      productVersion=currentMajorVersion,
                      withisos=withisos,
                      noisos=noisos,
                      overlay=overlay,
                      installSRType=installSRType,
                      suppackcds=suppackcds,
                      addToLogCollectionList=addToLogCollectionList,
                      ipv6=ipv6,
                      noipv4=noipv4,
                      extraConfig=extraConfig)
    # Leave the inputdir set for this version to properly handle any
    # updates needed later.
    xenrt.TEC().setInputDir(inputdir)
    host = upgradeHostViaVersionPath(host,
                                     string.join(versionPathList[1:]),
                                     currentVersion=currentVersion)
    return host

def upgradeHostViaVersionPath(host, versionPath, currentVersion=None):
    """Upgrade and/or update a host via the specified path."""
    versionPath = versionPath.replace(",", " ")
    versionPathList = versionPath.split()
    currentMajorVersion = host.productVersion
    if not currentVersion:
        # This is the variant that denotes whether this is a rollup or
        # beta etc. "Orlando/HF3" or "George/Beta" etc. If we know it,
        # e.g. becuse we were called by createHostViaVersionPath, then
        # use that otherwise default to the currentMajorVersion (e.g. "George")
        currentVersion = currentMajorVersion
    currentUpdates = []
    
    # Iterate through update/upgrades
    for i in range(len(versionPathList)):
        item = versionPathList[i]
        if item[0] == "+":
            item = item[1:]
            # It's an update
            xenrt.TEC().logverbose(\
                "upgradeHostViaVersionPath update %s with %s" %
                (currentMajorVersion, item))
            patchpath = productPatchPathForVersionPatch(\
                currentMajorVersion,
                item)
            patches = host.minimalList("patch-list")
            pfile = xenrt.TEC().getFile(patchpath)
            if not pfile:
                raise xenrt.XRTError("Unable to retrieve hotfix %s" %
                                     (patchpath))
            host.applyPatch(pfile, applyGuidance=True)
            patches2 = host.minimalList("patch-list")
            host.execdom0("xe patch-list")
            if len(patches2) <= len(patches):
                raise xenrt.XRTFailure("Patch list did not grow after patch "
                                       "application %s/%s" %
                                       (currentMajorVersion, item))
            currentUpdates.append(item)
        else:
            # version upgrade
            xenrt.TEC().logverbose(\
                "upgradeHostViaVersionPath upgrade %s (with updates %s) to %s"
                % (currentMajorVersion, str(currentUpdates), item))
            newVersion = item
            newMajorVersion = item.split("/")[0]
            inputdir = productInputdirForVersion(newVersion)
            xenrt.TEC().setInputDir(inputdir)
            newHost = host.upgrade(newMajorVersion)
            xenrt.TEC().registry.hostReplace(host, newHost)
            host = newHost
            currentMajorVersion = newMajorVersion
            currentVersion = newVersion
            currentUpdates = []

    xenrt.TEC().logverbose("upgradeHostViaVersionPath complete with host at "
                           "%s (with updates %s)" %
                           (currentVersion, str(currentUpdates)))
    return host

class SshInstallerThread(threading.Thread):
    def __init__(self, host, timeout, password):
        threading.Thread.__init__(self)
        self.stopnow = False
        self.deadline = xenrt.util.timenow() + timeout
        self.host = host
        self.password = password

    def run(self):
        while ((not self.stopnow) and (xenrt.util.timenow() < self.deadline)):
            xenrt.sleep(15) # Only try every 15 seconds
            if xenrt.ssh.SSH(self.host.getIP(),
                             "echo yes > /ssh_succeeded.txt",
                             password=self.password,
                             level=xenrt.RC_OK,
                             timeout=20,
                             username="root",
                             nowarn=True) == xenrt.RC_OK:
                return
        
    def stop(self):
        self.stopnow = True

class Host(xenrt.GenericHost):
    """Encapsulate a XenServer host."""

    SNMPCONF = "/etc/snmp/snmpd.conf"
    INSTALL_INTERFACE_SPEC = "MAC"
    LINUX_INTERFACE_PREFIX = "xenbr"
    USE_CCISS = True
    INITRD_REBUILD_SCRIPT = "new-kernel-pkg.py"
    SOURCE_ISO_FILES = {'source-1.iso': 'xe-phase-3', 'source-4.iso': 'xe-phase-3'}

    def __init__(self, machine, productVersion="Orlando", productType="xenserver"):
        xenrt.GenericHost.__init__(self,
                                   machine,
                                   productType=productType,
                                   productVersion=productVersion)
        self.cd = None
        self.compat = False
        self.pool = None
        self.dom0uuid = None
        self.templates = None
        self.uuid = None
        self.tailored = None
        self.bootLun = None
        self.bootNics = []
        self.distro = "XSDom0"

        self.i_cd = None
        self.i_primarydisk = None
        self.i_guestdisks = None
        self.i_source = None
        self.i_timezone = None
        self.i_interfaces = None
        self.i_ntpserver = None
        self.i_nameserver = None
        self.i_hostname = None
        self.i_extracds = None
        self.i_upgrade = None
        self.i_async = None
        self.i_suppackcds = None
        self.rebootingforbugtool = False
        self.defaultsr = None
        self.srs = {}
        self.lungroup = None
        self.special['no vncsnapshot on :0'] = True
        self.sharedDBlun = None
        self.logFetchExclude = ["/var/log/xen"]
        self.tileTemplates = {}
        self.tileLock = threading.Lock()
        self.netNameLock = threading.Lock()
        self.isOnline = True
        self.haLocalConfig = {}
        self.haStatefileBlocked = False
        self.haHeartbeatBlocks = {'allto': False,   'to': [], 
                                  'allfrom': False, 'from': []}
        self.special['Supports OEM install via host installer'] = True

        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTDom0Xen)
        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTSUnreclaim)
        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTSlab)
        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTPasswords)
        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTCoverage)
        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTCoresPerSocket)
        
        self.installationCookie = "%012x" % xenrt.random.randint(0,0xffffffffffff)

    def uninstallGuestByName(self, name):
        cli = self.getCLIInstance()
        try:
            cli.execute("vm-shutdown", "vm=\"%s\" --force" % name)
        except Exception, ex:
            xenrt.TEC().logverbose(str(ex))
        cli.execute("vm-uninstall", "vm=\"%s\" --force" % name)

    
    def getUptime(self):
        return float(self.execdom0("cat /proc/uptime").split()[0])

    def getInstallNetwork(self):
        return None

    def rebuildInitrd(self):
        """
        Rebuild the initrd of the host in-place
        This is virtually akin to applying a kernel hotfix
        The MD5 sums of the files should be different before and after

        Fingers crossed no reboot happens until the following 2 steps complete
        successfully or the machine will be trashed. There is away to avoid
        the below in clearwater and newer, but we'll need to do this for Tampa
        too. For clearwater and greater just need to do
        "sh initrd*.xen.img.cmd -f" without removing the original image file
        but the old-style way should work regardless of age
        """

        xenrt.TEC().logverbose("Rebuilding initrd for host %s..." % str(self))
        kernel = self.execdom0("uname -r").strip()
        imgFile = "initrd-{0}.img".format(kernel)
        xenrt.TEC().logverbose("Original md5sum = %s" %
                               self.execdom0("md5sum /boot/%s" % imgFile))
        xenrt.TEC().logverbose(
            "Removing boot image %s and rebuilding" % imgFile)
        self.execdom0("cd /boot")
        self.execdom0("rm -rf %s" % imgFile)
        self.execdom0('%s --install --package=kernel-xen --mkinitrd "$@" %s' % (self.INITRD_REBUILD_SCRIPT, kernel))

        xenrt.TEC().logverbose("New md5sum = %s" %
                               self.execdom0("md5sum /boot/%s" % imgFile))
        xenrt.TEC().logverbose("initrd has been rebuilt")

    @property
    def xapiObject(self):
        """Gets a XAPI Host object for this Host
        @return: A xenrt.lib.xenserver.XapiHost object for this Host
        @rtype: xenrt.lib.xenserver.XapiHost"""
        return xenrt.lib.xenserver.XapiHost(self.getCLIInstance(), self.uuid)

    def getPool(self):
        if not self.pool:
            poolFactory(self.productVersion)(self)
        return self.pool

    def populateSubclass(self, x):
        xenrt.GenericHost.populateSubclass(self, x)
        x.bootLun = self.bootLun
        x.bootNics = self.bootNics
        x.cd = self.cd
        x.compat = self.compat
        x.pool = self.pool
        if x.pool:
            x.pool.updateHostObject(self, x)
        x.i_cd = self.i_cd
        x.i_primarydisk = self.i_primarydisk
        x.i_guestdisks = self.i_guestdisks
        x.i_source = self.i_source
        x.i_timezone = self.i_timezone
        x.i_interfaces = self.i_interfaces
        x.i_ntpserver = self.i_ntpserver
        x.i_nameserver = self.i_nameserver
        x.i_hostname = self.i_hostname
        x.i_extracds = self.i_extracds
        x.i_upgrade = self.i_upgrade
        x.i_async = self.i_async
        x.i_suppackcds = self.i_suppackcds
        x.defaultsr = self.defaultsr
        x.srs = self.srs
        x.lungroup = self.lungroup
        x.sharedDBlun = self.sharedDBlun
        x.haLocalConfig = self.haLocalConfig
        x.haStatefileBlocked = self.haStatefileBlocked
        x.haHeartbeatBlocks = self.haHeartbeatBlocks

    def _clearObjectCache(self):
        """Remove cached object data."""
        xenrt.GenericHost._clearObjectCache(self)
        self.dom0uuid = None
        self.tileTemplates = {}
        self.defaultsr = None
        self.srs = {}

    def _getNetNameLock(self):
        if self.pool:
            return self.pool.master.netNameLock
        else:
            return self.netNameLock

    def getCLIInstance(self, local=False):
        if self.pool and not local:
            return self.pool.getCLIInstance()
        return xenrt.lib.xenserver.cli.getSession(self.machine)

    def createGuestObject(self, name):
        """Create a simple guest object."""
        return self.guestFactory()(name, "", self)

    def existing(self, doguests=True, guestsInRegistry=True):
        """Initialise this host object from an existing installed host"""
        # Check the management host address
        ip = self.execdom0("xe host-param-get uuid=%s param-name=address" %
                           (self.getMyHostUUID())).strip()
        if ip == "":
            xenrt.TEC().warning("%s doesn't have a management ip???" % self.getName())
        else:
            self.machine.ipaddr = ip
    
        self.guestconsolelogs = xenrt.TEC().lookup("GUEST_CONSOLE_LOGDIR")

        # Initialise guests
        if doguests:
            guests = self.listGuests()
            for guestname in guests:
                try:
                    guest = self.guestFactory()(guestname, None)
                    guest.existing(self)
                    xenrt.TEC().logverbose("Found existing guest: %s" % (guestname))
                    if guestsInRegistry:
                        xenrt.TEC().registry.guestPut(guestname, guest)
                except:
                    xenrt.TEC().logverbose("Could not load guest - perhaps it was deleted")
        self.distro = "XSDom0"

    def reinstall(self):
        self.install(cd=self.i_cd, primarydisk=self.i_primarydisk,
                     guestdisks=self.i_guestdisks, source=self.i_source, 
                     timezone=self.i_timezone, interfaces=self.i_interfaces,
                     ntpserver=self.i_ntpserver, nameserver=self.i_nameserver,
                     hostname=self.i_hostname, extracds=self.i_extracds,
                     upgrade=self.i_upgrade, async=self.i_async, 
                     suppackcds=self.i_suppackcds)
    
    def install(self,
                cd=None,
                primarydisk=None,
                guestdisks=["sda"],
                source="url",
                timezone="UTC",
                interfaces=[(None, "yes", "dhcp", None, None, None, None, None, None)],
                ntpserver=None,
                nameserver=None,
                hostname=None,
                extracds=None,
                upgrade=False,
                riotorio=False,
                async=False,
                installSRType=None,
                bootloader=None,
                overlay=None,
                suppackcds=None,
                **kwargs):    


        extrapi = ""
        if not upgrade:
            # Default for primary disk only if not an upgrade
            if not primarydisk:
                primarydisk = "sda"

            # Store the arguments for the reinstall and check commands
            self.i_cd = cd
            self.i_primarydisk = primarydisk
            self.i_guestdisks = guestdisks
            self.i_source = source
            self.i_timezone = timezone
            self.i_interfaces = interfaces
            self.i_ntpserver = ntpserver
            self.i_nameserver = nameserver
            self.i_hostname = hostname
            self.i_extracds = extracds
            self.i_upgrade = upgrade
            self.i_async = async
            self.i_suppackcds = suppackcds

        if upgrade:
            # Default to existing values if not specified
            if not primarydisk:
                if self.i_primarydisk:
                    primarydisk = self.i_primarydisk
                    # Handle the case where its a cciss disk going into a Dundee+ host with CentOS 6.4+ udev rules
                    # In this situation a path that includes cciss- will not work. See CA-121184 for details
                    if "cciss" in primarydisk:
                        primarydisk = self.getInstallDisk(ccissIfAvailable=self.USE_CCISS)
                    if "scsi-SATA" in primarydisk and self.isCentOS7Dom0():
                        primarydisk = self.getInstallDisk(legacySATA=False)
                else:
                    primarydisk = "sda"

            # Try to capture a bugtool before the upgrade
            try:
                xenrt.TEC().logverbose("Capturing bugtool before upgrade of %s"
                                       % (self.getName()))
                self.getBugTool()
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception getting bugtool before upgrade:"
                                    " %s" % (str(e)))

        # Check and lookup variables and files
        if not cd:
            imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
            xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
            imagePath = xenrt.TEC().lookup("CD_PATH_%s" % self.productVersion.upper(), 
                                           xenrt.TEC().lookup('CD_PATH', 'xe-phase-1'))
            cd = xenrt.TEC().getFile(os.path.join(imagePath, imageName), imageName)
        if not cd:
            raise xenrt.XRTError("No CD image supplied.")
        xenrt.checkFileExists(cd)
        self.cd = cd

        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
                                     
        comport = str(int(serport) + 1)
        xen_extra_args = self.lookup("XEN_EXTRA_ARGS", None)
        xen_extra_args_user = self.lookup("XEN_EXTRA_ARGS_USER", None)
        if xen_extra_args_user:
            xen_extra_args_user = string.replace(xen_extra_args_user, ",", " ")
        dom0_extra_args = self.lookup("DOM0_EXTRA_ARGS", None)
        dom0_extra_args_user = self.lookup("DOM0_EXTRA_ARGS_USER", None)
        ssh_key = xenrt.getPublicKey()
        root_password = self.lookup("ROOT_PASSWORD")
        self.password = root_password
        workdir = xenrt.TEC().getWorkdir()
        
        xenrt.TEC().progress("Starting installation of XenServer host on %s" %
                             (self.machine.name))
        
        # Get a PXE directory to put boot files in
        pxe = xenrt.PXEBoot(iSCSILUN = self.bootLun, ipxeInUse = self.lookup("USE_IPXE", False, boolean=True))
        use_mboot_img = xenrt.TEC().lookup("USE_MBOOT_IMG", False, boolean=True)
       
        # Pull installer boot files from CD image and put into PXE
        # directory
        xenrt.TEC().logverbose("Using ISO %s" % (cd))
        mount = xenrt.MountISO(cd)
        mountpoint = mount.getMount()
        pxe.copyIn("%s/boot/*" % (mountpoint))
        instimg = xenrt.TEC().lookup("CUSTOM_INSTALL_IMG", None)
        if instimg:
            pxe.copyIn(xenrt.TEC().getFile(instimg), "install.img")
        else:
            pxe.copyIn("%s/install.img" % (mountpoint))
        # For NetScaler SDX
        if use_mboot_img:
            imagePath = xenrt.TEC().lookup("CD_PATH_%s" % self.productVersion.upper(), 
                                           xenrt.TEC().lookup('CD_PATH', 'xe-phase-1'))
            pxe.copyIn(xenrt.TEC().getFile(os.path.join(imagePath, "mboot.img")), "mboot.img")
        # Copy installer packages to a web/nfs directory
        if source == "url":
            packdir = xenrt.WebDirectory()
            pidir = xenrt.WebDirectory()
        elif source == "nfs":
            packdir = xenrt.NFSDirectory()
            pidir = xenrt.NFSDirectory()
        else:
            raise xenrt.XRTError("Unknown install source method '%s'." %
                                 (source))
        if os.path.exists("%s/packages" % (mountpoint)):
            # Pre 0.4.3-1717 layout
            packdir.copyIn("%s/packages/*" % (mountpoint))
        else:
            # Split ISO layout
            packdir.copyIn("%s/packages.*" % (mountpoint))

        # If there's an XS-REPOSITORY-LIST, copy it in
        if os.path.exists("%s/XS-REPOSITORY-LIST" % (mountpoint)):
            packdir.copyIn("%s/XS-REPOSITORY-LIST" % (mountpoint))
            dstfile = "%s/XS-REPOSITORY-LIST" % packdir.dir
            os.chmod(dstfile, os.stat(dstfile)[stat.ST_MODE]|stat.S_IWUSR)

        # If we have any extra CDs, copy the extra packages as well
        if extracds:
            ecds = extracds
        else:
            ecds = self.getDefaultAdditionalCDList()
        if ecds:
            for ecdi in string.split(ecds, ","):
                if os.path.exists(ecdi):
                    # XRT-813 transition, remove this eventually
                    ecd = ecdi
                else:
                    ecd = xenrt.TEC().getFile("xe-phase-1/%s" % (os.path.basename(ecdi)),
                                              os.path.basename(ecdi))
                if not ecd:
                    raise xenrt.XRTError("Couldn't find %s." % (ecdi))
                xenrt.TEC().logverbose("Using extra CD %s" % (ecd))
                emount = xenrt.MountISO(ecd)
                emountpoint = emount.getMount()
                packdir.copyIn("%s/packages.*" % (emountpoint))
                emount.unmount()

        # If we have any supplemental pack CDs, copy their contents as well
        # and contruct the XS-REPOSITORY-LIST file
        if suppackcds is None:
            suppackcds = self.getSupplementalPackCDs()
        supptarballs = xenrt.TEC().lookup("SUPPLEMENTAL_PACK_TGZS", None)
        suppdirs = xenrt.TEC().lookup("SUPPLEMENTAL_PACK_DIRS", None)
        
        if suppackcds or supptarballs or suppdirs:
            repofile = "%s/XS-REPOSITORY-LIST" % (workdir)
            repo = file(repofile, "w")
            if os.path.exists("%s/XS-REPOSITORY-LIST" % (mountpoint)):
                f = file("%s/XS-REPOSITORY-LIST" % (mountpoint), "r")
                repo.write(f.read())
                f.close()
            if supptarballs:
                for supptar in supptarballs.split(","):
                    tarball = xenrt.TEC().getFile(supptar)
                    if not tarball:
                        tarball = xenrt.TEC().getFile("xe-phase-1/%s" % (supptar))
                    if not tarball:
                        tarball = xenrt.TEC().getFile("xe-phase-2/%s" % (supptar))
                    if not tarball:
                        raise xenrt.XRTError("Couldn't find %s." % (supptar))
                    xenrt.TEC().comment("Using supplemental pack tarball %s." % (tarball))
                    tdir = xenrt.TEC().tempDir()
                    xenrt.util.command("tar -zxf %s -C %s" % (tarball, tdir)) 
                    mnt = xenrt.MountISO("%s/*.iso" % (tdir))
                    extrapi = file("%s/post-install.sh" % (tdir)).read()
                    extrapi = re.sub("exit.*", "", extrapi)
                    packdir.copyIn("%s/*" % (mnt.getMount()),
                                   "/packages.%s/" % (os.path.basename(tarball).strip(".tgz")))
                    repo.write("packages.%s\n" % (os.path.basename(tarball).strip(".tgz")))
            if suppackcds:    
                for spcdi in string.split(suppackcds, ","):
                    # Try a fetch from the inputdir first
                    spcd = xenrt.TEC().getFile(spcdi)
                    if not spcd:
                        # Try the local test inputs
                        spcd = "%s/suppacks/%s" % (\
                            xenrt.TEC().lookup("TEST_TARBALL_ROOT"),
                            os.path.basename(spcdi))
                        if not os.path.exists(spcd):
                            raise xenrt.XRTError(\
                                "Supplemental pack CD not found locally or "
                                "remotely: %s" % (spcdi))
                            
                    xenrt.TEC().comment("Using supplemental pack CD %s" % (spcd))
                    spmount = xenrt.MountISO(spcd)
                    spmountpoint = spmount.getMount()
                    packdir.copyIn("%s/*" % (spmountpoint),
                                   "/packages.%s/" % (os.path.basename(spcdi)))
                    repo.write("packages.%s\n" % (os.path.basename(spcdi)))
            if suppdirs:
                for sd in string.split(suppdirs, ","):
                    tgz = xenrt.TEC().getFile(sd)
                    if not tgz:
                        raise xenrt.XRTError("Supplemental pack dir not found: %s" % sd)
                    t = xenrt.resources.TempDirectory()
                    xenrt.util.command("tar -C %s -xvzf %s" % (t.dir, tgz))
                    packdir.copyIn("%s/*" % t.dir, "/packages.%s/" % os.path.basename(tgz))
                    repo.write("packages.%s\n" % (os.path.basename(tgz)))
                    t.remove()
            repo.close()
            packdir.copyIn(repofile)
            xenrt.TEC().copyToLogDir(repofile,
                                     target="XS-REPOSITORY-LIST-%s" % self.getName())

        # Create an NFS directory for the installer to signal completion
        nfsdir = xenrt.NFSDirectory()

        # Create the installer answerfile
        guestdiskconfig = ""
        interfaceconfig = ""
        otherconfigs = ""
        
        # If we want to create the Local SR manually, set up the firstboot script here
        firstBootSRInfo = None
        if self.lookup("LOCAL_SR_POST_INSTALL", False, boolean=True): 
            defaultSRType = self.lookup("DEFAULT_SR_TYPE", "lvm")
            if installSRType:
                firstBootSRInfo = (guestdisks[0], installSRType)
            else:
                firstBootSRInfo = (guestdisks[0], self.lookup("INSTALL_SR_TYPE", defaultSRType))
            guestdisks = []
        
        if not upgrade:
            if xenrt.TEC().lookup('SR_ON_PRIMARY_DISK', True, boolean=True):
                pass
            else:
                guestdisks = list(set(guestdisks) - set([primarydisk]))
            for g in guestdisks:
                guestdiskconfig = guestdiskconfig + \
                                  ("<guest-disk>%s</guest-disk>\n" % (g))
            for i in interfaces:
                name, enabled, proto, ip, netmask, gateway, protov6, ip6, gw6 = i
                mac = None
                if name:
                    # If name is specifed then use the named interface
                    pass
                else:
                    # Otherwise use the configured default
                    if self.INSTALL_INTERFACE_SPEC == "MAC":
                        mac = self.lookup("MAC_ADDRESS", None)
                    if not mac:
                        name = self.getDefaultInterface()
                if mac:
                    spec = "hwaddr=\"%s\"" % (mac.lower())
                else:
                    spec = "name=\"%s\"" % (name)

                params = {'spec' : spec, 
                          'enabled' : enabled, 
                          'proto' : proto, 
                          'ip': ip, 
                          'netmask': netmask, 
                          'gateway' : gateway,
                          'protov6' : protov6, 
                          'ip6' : ip6, 
                          'gw6' : gw6}
                
                static_ipv6_info = ""
                if proto == "static":
                    if protov6 == "static":
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.ipv6_mode = protov6
                        self.setIP(params['ip6'])
                        static_ipv6_info = "<ipv6>%(ip6)s/64</ipv6>\n  <gatewayv6>%(gw6)s</gatewayv6>" % params
                    elif protov6 in set(["none", "dhcp", "autoconf"]):
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.ipv6_mode = protov6
                    else:
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s">""" % params
                    
                    params.update({'admin_interface' : admin_interface, 'static_ipv6_info': static_ipv6_info})
                    
                    interfaceconfig = interfaceconfig + """<interface %(spec)s enabled="%(enabled)s" proto="%(proto)s">
  <ip>%(ip)s</ip>
  <subnet-mask>%(netmask)s</subnet-mask>
  <gateway>%(gateway)s</gateway>
</interface>
%(admin_interface)s
  <ip>%(ip)s</ip>
  <subnet-mask>%(netmask)s</subnet-mask>
  <gateway>%(gateway)s</gateway>
  %(static_ipv6_info)s
</admin-interface>
""" % params 
                else:
                    if protov6 == "static":
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.ipv6_mode = protov6
                        self.setIP(params['ip6'])
                        static_ipv6_info = "<ipv6>%(ip6)s/64</ipv6>\n  <gatewayv6>%(gw6)s</gatewayv6>" % params
                    elif protov6 in set(["none", "dhcp", "autoconf"]):
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.ipv6_mode = protov6
                    else:
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s">""" % params

                    static_ipv6_info = static_ipv6_info + "\n"
                    params.update({'admin_interface' : admin_interface, 'static_ipv6_info': static_ipv6_info})
                    
                    interfaceconfig = interfaceconfig + '<interface %(spec)s enabled="%(enabled)s" proto="%(proto)s"/>\n%(admin_interface)s\n  %(static_ipv6_info)s</admin-interface>' % params 
            if self.ipv6_mode == "autoconf":
                self.setIP(self.getIPv6AutoconfAddress())
            elif self.ipv6_mode == "dhcp":
                (_, _, _, ip6, _) = self.getNICAllocatedIPAddress(0, also_ipv6=True)
                self.setIP(ip6)
            elif self.ipv6_mode == "none" or self.ipv6_mode is None:
                self.use_ipv6 = False
                
            if nameserver:
                otherconfigs = otherconfigs + ("<nameserver>%s</nameserver>\n" %
                                               (nameserver))
            if ntpserver:
                otherconfigs = otherconfigs + ("<ntp-servers>%s</ntp-servers>\n" %
                                               (ntpserver))
            if hostname:
                otherconfigs = otherconfigs + ("<hostname>%s</hostname>\n" %
                                               (hostname))

        if upgrade:
            ansfile = "%s/%s-upgrade.xml" % (workdir, self.getName())
        else:
            ansfile = "%s/%s-install.xml" % (workdir, self.getName())
        ans = file(ansfile, "w")
        if source == "nfs":
            url = packdir.getMountURL("")
            purl = pidir.getURL("post-install-script-%s" % (self.getName()))
            furl = pidir.getURL("install-failed-script-%s" % (self.getName()))
            pextra = ""
        else:
            url = packdir.getURL("")
            purl = pidir.getURL("post-install-script-%s" % (self.getName()))
            furl = pidir.getURL("install-failed-script-%s" % (self.getName()))
            pextra = ""
        if upgrade:
            installationExtras = " mode=\"upgrade\""
        elif riotorio:
            installationExtras = " mode=\"reinstall\""
        else:
            installationExtras = ""
            # If a local SR type if not specified then normally we don't
            # specify it in the answerfile and rely on the product default.
            # We can override this behaviour by specifying a default in
            # DEFAULT_SR_TYPE. This can still be overriden by the srtype
            # argument to this method or the INSTALL_SR_TYPE variable
            # (generally used in a sequence file)
            defaultSRType = self.lookup("DEFAULT_SR_TYPE", None)
            if installSRType:
                srtype = installSRType
            else:
                srtype = self.lookup("INSTALL_SR_TYPE", defaultSRType)
            if srtype:
                installationExtras = installationExtras + " srtype='%s'" % (srtype)
        if upgrade or riotorio:
            storage = """<existing-installation>%s</existing-installation>""" \
                % (primarydisk)
        else:
            primarydiskconfig = """<primary-disk gueststorage="no">%s</primary-disk>""" % primarydisk
            storage = """%s
%s
""" % (primarydiskconfig, guestdiskconfig)
        if upgrade:
            rpassword = ""
        else:
            rpassword = "<root-password>%s</root-password>" % (root_password)
        if bootloader:
            bl = "<bootloader>%s</bootloader>" % (bootloader)
        else:
            bl = ""

        network_backend = xenrt.TEC().lookup("NETWORK_BACKEND", None)
        if network_backend:
            otherconfigs = otherconfigs + ("<network-backend>%s</network-backend>\n"
                                           % (network_backend))

        if xenrt.TEC().lookup("CC_ENABLE_SSH", False, boolean=True):
            otherconfigs = otherconfigs + "<service name=\"sshd\" state=\"enabled\"/>\n"

        driverDisk = xenrt.TEC().lookup("DRIVER_DISK", None)
        if driverDisk:
            driverWebDir = xenrt.WebDirectory() 
            xenrt.TEC().logverbose("Using driver disk %s" % driverDisk)
            cd = xenrt.TEC().getFile(driverDisk)
            if not cd:
                raise xenrt.XRTError("Cannot find driver disk %s" % driverDisk)
            driverMount = xenrt.MountISO(cd)
            driverMountPoint = driverMount.getMount()
            driverWebDir.copyIn("%s/*" % driverMountPoint)
            otherconfigs += ("<driver-source type=\"url\">%s</driver-source>\n" % \
                             (driverWebDir.getURL("")))

        anstext = """<?xml version="1.0"?>
<installation%s>
%s
%s
%s
%s
<source type="%s">%s</source>
<timezone>%s</timezone>
<post-install-script%s>%s</post-install-script>
<install-failed-script>%s</install-failed-script>
%s
</installation>
""" % (installationExtras,
       bl,
       storage,
       interfaceconfig,
       rpassword,
       source,
       url,
       timezone,
       pextra,
       purl,
       furl,
       otherconfigs)
        ans.write(anstext)
        ans.close()
        packdir.copyIn(ansfile)
        xenrt.TEC().copyToLogDir(ansfile)
    
        # Create the installer post-install script
        xapiargs = xenrt.TEC().lookup("XAPI_EXTRA_ARGS", None)
        if xapiargs:
            xenrt.TEC().warning("Using extra args to xapi: %s" % (xapiargs))
            xapitweak = """# Add extra command line args to xapi
mv etc/init.d/xapi etc/init.d/xapi.origtweak
sed -e's#/opt/xensource/bin/xapi#/opt/xensource/bin/xapi %s#' < etc/init.d/xapi.origtweak > etc/init.d/xapi
chmod 755 etc/init.d/xapi
""" % (xapiargs)
        else:
            xapitweak = ""
            
        xapi_log_tweak = ""
        if xenrt.TEC().lookup('DEBUG_CA65062', False, boolean=True):
            xenrt.TEC().warning("Turning xapi redo_log logging ON")
            xapi_log_tweak = """#Turn xapi redo_log logging ON
mv etc/xensource/log.conf etc/xensource/log.conf.orig
sed -e 's/debug;redo_log;nil/#debug;redo_log;nil/' < etc/xensource/log.conf.orig > etc/xensource/log.conf
"""
        mods = []
        # Common substitutions.
        mods.append('-e"s/ com.=/ com%s=/"' % (comport))
        mods.append('-e"s/console=com./console=com%s/"' % (comport))
        mods.append('-e"s/ttyS./ttyS%s/g"' % (serport))
        dom0mem = xenrt.TEC().lookup("OPTION_DOM0_MEM", None)
        if dom0mem:
            mods.append("-e's/dom0_mem=\S+/dom0_mem=%sM/'" % (dom0mem))
        if xenrt.TEC().lookup("OPTION_DEBUG", False, boolean=True):
            mods.append('-e"s/ ro / ro print-fatal-signals=2 /"')
        mods.append('-e"s/115200/%s/g"' % (serbaud))
        mods.append('-e"s/9600/%s/g"' % (serbaud))

        extmods = list(mods)
        # Substitutions for extlinux.conf.
        extmods.append("-e's/^default xe.*/default xe-serial/'")
        if xenrt.TEC().lookup("OPTION_DEBUG", False, boolean=True):
            extmods.append('-e"s/(append .*xen\S*.gz)/\\1 loglvl=all guest_loglvl=all/"')
        if dom0_extra_args:
            extmods.append('-e"s#(--- /boot/vmlinuz\S*)#\\1 %s#"' %
                            (dom0_extra_args))
        if dom0_extra_args_user:
            extmods.append('-e"s#(--- /boot/vmlinuz\S*)#\\1 %s#"' %
                            (dom0_extra_args_user))
        if xen_extra_args:
            extmods.append('-e"s#(append .*xen\S*.gz)#\\1 %s#"' %
                            (xen_extra_args))
        if xen_extra_args_user:
            extmods.append('-e"s#(append .*xen\S*.gz)#\\1 %s#"' %
                            (xen_extra_args_user))
        if self.lookup("XEN_DISABLE_WATCHDOG", False, boolean=True):
            extmods.append(r'-e "s#(/boot/xen.*)watchdog_timeout=[0-9]+(.*/boot/vmlinuz)#\1watchdog=false\2#" ')
        grubmods = list(mods)
        # Substitutions for grub.conf.
        grubmods.append("-e's/^default 0/default 1/'")
        if xenrt.TEC().lookup("OPTION_DEBUG", False, boolean=True):
            grubmods.append('-e"s/(kernel .*xen\S*.gz)/\\1 loglvl=all guest_loglvl=all/"')
        if dom0_extra_args:
            grubmods.append('-e"s#(module /boot/vmlinuz\S*)#\\1 %s#"' %
                            (dom0_extra_args))
        if dom0_extra_args_user:
            grubmods.append('-e"s#(module /boot/vmlinuz\S*)#\\1 %s#"' %
                            (dom0_extra_args_user))
        if xen_extra_args:
            grubmods.append('-e"s#(kernel .*xen\S*.gz)#\\1 %s#"' %
                            (xen_extra_args))
        if xen_extra_args_user:
            grubmods.append('-e"s#(kernel .*xen\S*.gz)#\\1 %s#"' %
                            (xen_extra_args_user))
        forcedev = self.lookup("FORCE_GRUB_DEVICE", None)
        if forcedev:
            forcedev = string.replace(forcedev, ")", "\)")
            forcedev = string.replace(forcedev, "(", "\(")
            grubmods.append('-e"s/\(hd[[:digit:]]+,[[:digit:]]+\)/%s/"' %
                           (forcedev))

        dom0cpus = xenrt.TEC().lookup("OPTION_XE_SMP_DOM0", None)
        if dom0cpus:
            xenrt.TEC().logverbose("Using %s CPUs in Domain-0." % (dom0cpus))
            unplugcpus = """
cp etc/init.d/unplug-vcpus root/unplug-vcpus.bak
CPUS=0
for i in /sys/devices/system/cpu/cpu*; do
    CPUS=$[ $CPUS + 1 ]
done

if [ "%s" == "ALL" ]; then
    DISABLEFROM=${CPUS} 
else
    DISABLEFROM=%s
fi

cat root/unplug-vcpus.bak | \
    sed -e "s/\/sys\/devices\/system\/cpu\/cpu\*/\`seq ${DISABLEFROM} $[ ${CPUS} - 1 ]\`/" \
        -e "s/\$i/\/sys\/devices\/system\/cpu\/cpu\$i/g" > etc/init.d/unplug-vcpus
""" % (dom0cpus, dom0cpus)
        else:
            unplugcpus = ""
        
        blacklist = self.lookup("BLACKLIST_DRIVERS", None)
        if blacklist:
            blacklistdrivers = "echo -e \"%s\" > etc/modprobe.d/xrtblacklist.conf" % string.join(["blacklist %s" % x for x in blacklist.split(",")],"\\n")
        else:
            blacklistdrivers = ""

        if xenrt.TEC().lookup("OPTION_STATE_HACK", False, boolean=True):
            statehack = """# Hack to put state.db on another partition
mkfs.ext3 /dev/sda2
if [ -d var/xapi ]; then 
  mkdir /tmp/statehack
  mount /dev/sda2 /tmp/statehack
  mv var/xapi/* /tmp/statehack
  umount /tmp/statehack
else
  mkdir -p var/xapi
fi
echo "/dev/sda2 /var/xapi ext3 defaults 0 0" >> etc/fstab
echo "%s!/bin/bash" > statgen.sh
echo "TS=\\$(date +%%s)" >> statgen.sh
echo "STATS=\\$(cat /sys/block/sda/sda2/stat)" >> statgen.sh
echo 'echo $TS $STATS' >> statgen.sh
chmod +x statgen.sh
echo "* * * * * root /statgen.sh >> /var/log/statehack.log" >> etc/crontab
""" % ('#')
        else:
            statehack = ""

        if overlay:
            overlaynfsurl = overlay.getMountURL("")
        else:
            overlaynfsurl = ""

        if xenrt.TEC().lookup("TEST_INSTALLER_SSHPW", None) is not None:
            installer_ssh = "if [ -f /ssh_succeeded.txt ]; then cp /ssh_succeeded.txt .; fi"
        else:
            installer_ssh = ""

        # Hack SM backend links
        smhackstxt = ""        
        smhacks = self.lookup("SMHACK", None)
        if smhacks:
            for srfile in smhacks.keys():
                # SMHACK/LVMSR=LVMSR.py
                srtarget = smhacks[srfile]
                smhackstxt = smhackstxt + """
# Relinking %s to %s
rm -f opt/xensource/sm/%s
ln -s %s opt/xensource/sm/%s
""" % (srfile, srtarget, srfile, srtarget, srfile)

        # Hack for different dom0 static memory allocation
        dom0memhack = ""
        dom0mem = xenrt.TEC().lookup("DOM0_MEM", None)
        if dom0mem:
            dom0memhack = """
# Set the dom0 memory allocation
sed -i 's/dom0_mem=[0-9]*M/dom0_mem=%sM/g' boot/extlinux.conf
# Keeping what we just set to dom0_mem, also change ',max:xxxM' if it's there
sed -i 's/dom0_mem=\([0-9]*\)M,max:[0-9]*M/dom0_mem=\\1M,max:%sM/g' boot/extlinux.conf
""" % (dom0mem, dom0mem)

        # Hack for a different ramdisk size
        dom0rdsizehack = ""
        dom0rdsize = xenrt.TEC().lookup("DOM0_RDSIZE", None)
        if dom0rdsize:
            dom0rdsizehack = """
# Set the dom0 ramdisk size
awk -F'---' {'if (NF==3) {print $1 "---" $2 "ramdisk_size=%s ---" $3} else print $0'} boot/extlinux.conf > /tmp/rdsizeboot.tmp
mv /tmp/rdsizeboot.tmp boot/extlinux.conf
""" % (dom0rdsize)

        # Hack for a different blkback max_ring_page_order
        dom0blkbkorderhack = ""
        dom0blkbkorder = xenrt.TEC().lookup("DOM0_BLKBKORDER", None)
        if dom0blkbkorder:
            dom0blkbkorderhack = """
# Set the dom0 blkback max_ring_page_order
awk -F'---' '{if (NF==3) {print $1 " --- " $2 " blkbk.max_ring_page_order=%s --- " $3} else print $0}' boot/extlinux.conf > /tmp/blkbkorderhack.tmp
mv /tmp/blkbkorderhack.tmp boot/extlinux.conf
""" % (dom0blkbkorder)

        # Hack for a different blkback reqs parameter (use only on Sanibel and older versions)
        dom0blkbkreqshack = ""
        dom0blkbkreqs = xenrt.TEC().lookup("DOM0_BLKBKREQS", None)
        if dom0blkbkreqs:
            dom0blkbkreqshack = """
# Set the dom0 blkback reqs parameter
awk -F'---' '{if (NF==3) {print $1 " --- " $2 " blkbk.reqs=%s --- " $3} else print $0}' boot/extlinux.conf > /tmp/blkbkreqshack.tmp
mv /tmp/blkbkreqshack.tmp boot/extlinux.conf
""" % (dom0blkbkreqs)

        # Hack sm to assign mempools per vdi and not sr
        dom0mempoolhack = ""
        dom0mempool = xenrt.TEC().lookup("DOM0_MEMPOOL", None)
        if dom0mempool:
            dom0mempoolhack = """
cat << _EOF_ >> /tmp/mempool.patch
--- a/blktap2.py        2012-04-25 17:48:20.000000000 +0100
+++ b/blktap2.py        2012-04-25 17:48:57.000000000 +0100
@@ -35,7 +35,13 @@
 PLUGIN_TAP_PAUSE = "tapdisk-pause"
 
 NUM_PAGES_PER_RING = 32 * 11
-MAX_FULL_RINGS = 8
+
+def getmaxringpages():
+    order = int(open("/sys/module/blkbk/parameters/max_ring_page_order", "r").readline())
+    maxringpages = 1 << order
+    return maxringpages
+
+MAX_FULL_RINGS = getmaxringpages()
 
 ENABLE_MULTIPLE_ATTACH = "/etc/xensource/allow_multiple_vdi_attach"
 NO_MULTIPLE_ATTACH = not (os.path.exists(ENABLE_MULTIPLE_ATTACH)) 
@@ -1414,7 +1420,7 @@
 
         dev_path = self.setup_cache(sr_uuid, vdi_uuid, caching_params)
         if not dev_path:
-            self._set_blkback_pool(sr_uuid)
+            self._set_blkback_pool(vdi_uuid)
             phy_path = self.PhyLink.from_uuid(sr_uuid, vdi_uuid).readlink()
             # Maybe launch a tapdisk on the physical link
             if self.tap_wanted():
_EOF_
cd /opt/xensource/sm
patch -p1 < /tmp/mempool.patch
cd -
"""

        # Since CP-5922, both a debug-enabled and a debug-disabled build of Xen are installed.
        # Optionally choose to employ the debug-disabled build by swizzling symlinks in /boot.
        usenondebugxen = ""
        if xenrt.TEC().lookup("FORCE_NON_DEBUG_XEN", None):
            usenondebugxen = self.swizzleSymlinksToUseNonDebugXen(pathprefix="")

        firstBootSRSetup = ""
        if firstBootSRInfo:
            (disk, srtype) = firstBootSRInfo
            firstBootSRSetup = """
rm -f /etc/udev/rules.d/61-xenrt.rules
rm -f /dev/disk/by-id/*
if [ -e /sbin/udevadm ]
then
    sleep 5
    /sbin/udevadm trigger --action=add
    /sbin/udevadm settle
    sleep 5
    export XRTDISKLINKS=$(/sbin/udevadm info -q symlink -n %s)
else
    export XRTDISKLINKS=$(udevinfo -q symlink -n %s)
fi
echo $XRTDISKLINKS
export XRTDISK=$(echo -n $XRTDISKLINKS | awk '{ for (i=1; i<=NF; i++) { if (index($i, "disk/by-id") == 1 && index($i, "disk/by-id/edd") == 0 && index($i, "disk/by-id/wwn") == 0)  print $i;}}')
echo $XRTDISK

echo XSPARTITIONS=\\'/dev/$XRTDISK\\' >> etc/firstboot.d/data/default-storage.conf
echo XSTYPE='%s' >> etc/firstboot.d/data/default-storage.conf
echo PARTITIONS=\\'/dev/$XRTDISK\\' >> etc/firstboot.d/data/default-storage.conf
echo TYPE='%s' >> etc/firstboot.d/data/default-storage.conf
""" % (disk, disk, srtype, srtype)

        pifile = "%s/post-install-script-%s" % (workdir,self.getName())
        pi = file(pifile, "w")
        pitext = """#!/bin/bash
#
# This post-install-script hook calls this with the argument being the
# mount point of the dom0 filesystem

set -x

cd $1

# Fix up the bootloader configuration.
if [ -e boot/extlinux.conf ]; then
    mv boot/extlinux.conf boot/extlinux.conf.orig
    sed -r %s < boot/extlinux.conf.orig > boot/extlinux.conf
else
    mv boot/grub/menu.lst boot/grub/menu.lst.orig
    sed -r %s < boot/grub/menu.lst.orig > boot/grub/menu.lst
fi

if [ -d root ]; then
    ROOT=root
elif [ -d rws/root ]; then
    ROOT=rws/root
else
    ROOT=root
fi

mkdir -p $ROOT/.ssh
chmod 700 $ROOT/.ssh
echo '%s' > $ROOT/.ssh/authorized_keys
chmod 600 $ROOT/.ssh/authorized_keys

# Allow the agent to dump core
mv etc/init.d/xapi etc/init.d/xapi.orig
awk '{print;if(FNR==1){print "DAEMON_COREFILE_LIMIT=unlimited"}}' < etc/init.d/xapi.orig > etc/init.d/xapi
chmod 755 etc/init.d/xapi

%s
%s
%s
%s
%s
%s
%s
%s
%s
%s
%s
%s
%s
%s

# Apply an overlay if we have one
if [ -n "%s" ]; then
    mkdir /tmp/xenrtoverlaymount
    mount -t nfs %s /tmp/xenrtoverlaymount
    tar -cvf - -C /tmp/xenrtoverlaymount . | tar -xvf - -C $1
    umount /tmp/xenrtoverlaymount
fi

# If we know we have a USB stick in this box dd zeros on to it to make sure
# it doesn't boot
if [ -n "%s" ]; then
    dd if=/dev/zero of=/dev/%s count=1024
fi

# Write a XenRT Insallation cookie
echo '%s' > $ROOT/xenrt-installation-cookie 
service sshd stop || true
# Signal XenRT that we've finished
mkdir /tmp/xenrttmpmount
mount -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
sleep 30

""" % (string.join(extmods),
       string.join(grubmods),
       ssh_key,
       xapitweak,
       xapi_log_tweak,
       statehack,
       unplugcpus,
       smhackstxt,
       installer_ssh,
       dom0memhack,
       dom0rdsizehack,
       dom0blkbkorderhack,
       dom0blkbkreqshack,
       dom0mempoolhack,
       usenondebugxen,
       blacklistdrivers,
       firstBootSRSetup,
       overlaynfsurl,
       overlaynfsurl,
       self.lookup("USB_BOOT_DEVICE", ""),
       self.lookup("USB_BOOT_DEVICE", ""),
       self.installationCookie,
       nfsdir.getMountURL(""))
        pi.write(pitext)
        pi.close()
        pidir.copyIn(pifile)
        xenrt.TEC().copyToLogDir(pifile)

        # Create a script to run on install failure (on builds that
        # support this)
        fifile = "%s/install-failed-script-%s" % (workdir,self.getName())
        fi = file(fifile, "w")
        fitext = """#!/bin/bash

# The arguments to this script have changed in Bodie. It will be called
# for both a successful and failed install. The first (and only) command line
# argument is 0 for success and 1 for failure.

if [ "$1" = "0" ]; then
    
    %s
    
    # Bodie mode, this was a successful installation
    echo "Successful install, not running fail commands."
    exit 0
fi

# For a short period there was an extra argument in Bodie builds, support
# this mode too.
if [ "$1" = "installation-complete" ]; then
    # Old Bodie mode, if this is a success then exit so the rest of the script
    # can be used for the failure case
    if [ "$2" = "0" ]; then
        # Success
        echo "Successful install, not running fail commands."
        exit 0
    fi    
fi
        
# Signal XenRT that we've failed
mkdir /tmp/xenrttmpmount
mount -t nfs %s /tmp/xenrttmpmount
echo "Failed install" > /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
cat /proc/partitions >> /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
for i in /sys/block/*/device/vendor; do echo $i; cat $i; done >> /tmp/failedinstall
for i in /sys/block/*/device/model; do echo $i; cat $i; done >> /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
if [ -x /opt/xensource/installer/report.py ]; then
  /opt/xensource/installer/report.py file:///tmp/xenrttmpmount/
fi
cat /tmp/failedinstall /tmp/install-log > /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount

# if we have atexit=shell specified, we should exit 
grep 'atexit=shell' /proc/cmdline &> /dev/null && exit 0

# Now stop here so we don't boot loop
while true; do
    sleep 30
done
""" % (extrapi, nfsdir.getMountURL(""))
        fi.write(fitext)
        fi.close()
        pidir.copyIn(fifile)
        xenrt.TEC().copyToLogDir(fifile)

        # Set the boot files and options for PXE
        if self.lookup("PXE_NO_SERIAL", False, boolean=True):
            pxe.setSerial(None,None)
        else:
            pxe.setSerial(serport, serbaud)
        if self.lookup("PXE_NO_PROMPT", False, boolean=True):
            pxe.setPrompt("0")
        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")
        if use_mboot_img:
            pxecfg = pxe.addEntry("carboninstall", default=1, boot="mbootimg")
        else:
            pxecfg = pxe.addEntry("carboninstall", default=1, boot="mboot")
        xenfiles = glob.glob("%s/boot/xen*" % (mountpoint))
        xenfiles.extend(glob.glob("%s/boot/xen.gz" % (mountpoint)))
        if len(xenfiles) == 0:
            raise xenrt.XRTError("Could not find a xen* file to boot")
        xenfile = os.path.basename(xenfiles[-1])
        kernelfiles = glob.glob("%s/boot/vmlinuz*" % (mountpoint))
        if len(kernelfiles) == 0:
            raise xenrt.XRTError("Could not find a vmlinuz* file to boot")
        kernelfile = os.path.basename(kernelfiles[-1])

        if use_mboot_img:
            pass
        else:
            pxecfg.mbootSetKernel(xenfile)
            pxecfg.mbootSetModule1(kernelfile)
            pxecfg.mbootSetModule2("install.img")
        
        pxecfg.mbootArgsKernelAdd("watchdog")
        pxecfg.mbootArgsKernelAdd("com%s=%s,8n1" % (comport, serbaud))
        if isinstance(self, xenrt.lib.xenserver.MNRHost):
            pxecfg.mbootArgsKernelAdd("console=com%s,vga" % (comport))
        else:
            pxecfg.mbootArgsKernelAdd("console=com%s,tty" % (comport))
        if isinstance(self, xenrt.lib.xenserver.TampaHost):
            pxecfg.mbootArgsKernelAdd("dom0_mem=752M,max:752M")
        else:
            pxecfg.mbootArgsKernelAdd("dom0_mem=752M")
        pxecfg.mbootArgsKernelAdd("dom0_max_vcpus=2")
        if xen_extra_args:
            pxecfg.mbootArgsKernelAdd(xen_extra_args)
            xenrt.TEC().warning("Using installer extra Xen boot args %s" %
                                (xen_extra_args))
        if xen_extra_args_user:
            pxecfg.mbootArgsKernelAdd(xen_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Xen boot args %s" %
                                (xen_extra_args_user))
        
        pxecfg.mbootArgsModule1Add("root=/dev/ram0")
        if self.special.has_key("dom0 uses hvc") and \
               self.special["dom0 uses hvc"]:
            pxecfg.mbootArgsModule1Add("console=tty0")
            pxecfg.mbootArgsModule1Add("xencons=hvc")
            pxecfg.mbootArgsModule1Add("console=hvc0")
        else:
            pxecfg.mbootArgsModule1Add("console=tty0")
            pxecfg.mbootArgsModule1Add("console=ttyS%s,%sn8" %
                                       (serport, serbaud))
        pxecfg.mbootArgsModule1Add("ramdisk_size=65536")
        pxecfg.mbootArgsModule1Add("install")
        
        if not xenrt.TEC().lookup("OPTION_NO_ANSWERFILE", False, boolean=True):
            if upgrade:
                pxecfg.mbootArgsModule1Add("rt_answerfile=%s" %
                                           (packdir.getURL("%s-upgrade.xml" %
                                                           (self.getName()))))
            else:
                pxecfg.mbootArgsModule1Add("rt_answerfile=%s" %
                                           (packdir.getURL("%s-install.xml" %
                                                           (self.getName()))))
        
        pxecfg.mbootArgsModule1Add("output=ttyS0")

        mac = self.lookup("MAC_ADDRESS", None)
        if mac:
            pxecfg.mbootArgsModule1Add("answerfile_device=%s" % (mac))
        if self.lookup("FORCE_NIC_ORDER", False, boolean=True):
            nics = [0]
            nics.extend(self.listSecondaryNICs())
            for n in nics:
                pxecfg.mbootArgsModule1Add("map_netdev=eth%u:s:%s" % (n, self.getNICMACAddress(n)))
        if dom0_extra_args:
            pxecfg.mbootArgsModule1Add(dom0_extra_args)
            xenrt.TEC().warning("Using installer extra Dom0 boot args %s" %
                                (dom0_extra_args))
        if dom0_extra_args_user:
            pxecfg.mbootArgsModule1Add(dom0_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Dom0 boot args %s"
                                % (dom0_extra_args_user))
        if xenrt.TEC().lookup("OPTION_BASH_SHELL", False, boolean=True):
            pxecfg.mbootArgsModule1Add("bash-shell")

        if self.bootLun:
            pxecfg.mbootArgsModule1Add("use_ibft")
            xenrt.TEC().logverbose("Booting RAM disk Linux to discover NIC PCI locations")
            try:
                self.bootRamdiskLinux()
            except Exception, e:
                xenrt.TEC().logverbose("Couldn't boot RAM disk Linux to discover NIC PCI locations: %s" % str(e))
                raise xenrt.XRTError("Failed to boot RAM disk Linux to discover NIC PCI locations")
            pxe.clearISCSINICs()
            for b in self.bootNics:
                mac = self.getNICMACAddress(b)
                # Find the PCI bus, device and function from sysfs, using the MAC
                device = self.execdom0("grep -li \"%s\" /sys/class/net/*/address | cut -d \"/\" -f 5" % mac).strip()
                pcilocation = self.execdom0("grep PCI_SLOT_NAME /sys/class/net/%s/device/uevent | cut -d \"=\" -f 2" % device).strip()
                m = re.match("[0-9a-fA-F]{4}:([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-9a-fA-F])", pcilocation)
                bus = int(m.group(1), 16)
                device = int(m.group(2), 16)
                function = int(m.group(3), 16)

                # IBFT spec for PCI device is:
                #   8 Bits: PCI Bus
                #   5 Bits: PCI Device
                #   3 Bits: PCI Function
                ibftpci = bus*256 + device*8 + function
                pxe.addISCSINIC(b, ibftpci)

        ssh_pw = xenrt.TEC().lookup("TEST_INSTALLER_SSHPW", None)
        if ssh_pw:
            pxecfg.mbootArgsModule1Add("sshpassword=%s"%ssh_pw)
        # TODO re-enable SSH once worked out how to stop XenRT thinking the host has booted
        #elif not xenrt.TEC().lookup("NO_INSTALLER_SSH", False, boolean=True):
        #    # Enable SSH into the installer to aid debug if installations fail
        #    pxecfg.mbootArgsModule1Add("sshpassword=%s" % self.password)
        
        optionRootMpath = self.lookup("OPTION_ROOT_MPATH", None)
        
        if optionRootMpath != None and len(optionRootMpath) > 0:
            pxecfg.mbootArgsModule1Add("device_mapper_multipath=%s" % optionRootMpath)

        # Set up PXE for installer boot
        pxefile = pxe.writeOut(self.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))
        if self.bootLun:
            ipxefile = pxe.writeISCSIConfig(self.machine)
            ipfname = os.path.basename(ipxefile)
            xenrt.TEC().copyToLogDir(ipxefile,target="%s.ipxe.txt" % (ipfname))

        # We're done with the ISO now
        mount.unmount()
        
        # Reboot the host into the installer
        if self.lookup("INSTALL_DISABLE_FC", False, boolean=True):
            self.disableAllFCPorts()
        if upgrade:
            self._softReboot()
        else:
            self.machine.powerctl.cycle()
            
        xenrt.TEC().progress("Rebooted host to start installation.")
        if async:
            handle = (nfsdir, None, pxe, False) # Not UEFI
            return handle
        handle = (nfsdir, packdir, pxe, False) # Not UEFI
        if xenrt.TEC().lookup("OPTION_BASH_SHELL", False, boolean=True):
            xenrt.TEC().tc.pause("Pausing due to bash-shell option")
            
        
        
        # this option allows manual installation i.e. you step through
        # the XS installer manually and it detects for when this is finished.
        if xenrt.TEC().lookup("OPTION_NO_ANSWERFILE", False, boolean=True):
            
            xenrt.TEC().logverbose("User is to step through installer manually")
            xenrt.TEC().logverbose("Waiting 5 mins")
            
            # wait 5 mins
            xenrt.sleep(5 * 60)
           
            # now fix-up the pxe file for local boot
            xenrt.TEC().logverbose("Setting PXE file to be local boot by default")
            pxe.setDefault("local")
            pxe.writeOut(self.machine)
            if self.bootLun:
                pxe.writeISCSIConfig(self.machine, boot=True)
            
            # now wait for SSH to come up. Allow an hour for the installer
            # to be completed manually
            self.waitForSSH(3600, desc="Host boot (!%s)" % (self.getName()))

            self.installComplete(handle, waitfor=False, upgrade=upgrade)
        else:
            self.installComplete(handle, waitfor=True, upgrade=upgrade)

        if xenrt.TEC().lookup("USE_HOST_IPV6", False, boolean=True):
            xenrt.TEC().logverbose("Setting %s's primary address type as IPv6" % self.getName())
            pif = self.execdom0('xe pif-list management=true --minimal').strip()
            self.execdom0('xe host-management-disable')
            self.execdom0('xe pif-set-primary-address-type primary_address_type=ipv6 uuid=%s' % pif)
            self.execdom0('xe host-management-reconfigure pif-uuid=%s' % pif)
            self.waitForSSH(300, "%s host-management-reconfigure (IPv6)" % self.getName())

        return None

    # Change the timestamp formatting in syslog
    # For rsyslog (in Dundee):
    # - TraditionalFileFormat: 1s resolution, default backwards compatible format
    # - FileFormat: us resolution, useful for precise measurement of events in tests
    def changeSyslogFormat(self, new="TraditionalFileFormat"):
        orig="TraditionalFileFormat"
        self.execdom0("sed -i 's/RSYSLOG_%s/RSYSLOG_%s/' /etc/rsyslog.conf" % (orig, new) )
        self.execdom0("service rsyslog restart")

    def swizzleSymlinksToUseNonDebugXen(self, pathprefix):
            return """
# Use the build of xen with debugging disabled
# Only swizzle if /boot/xen-debug.gz exists and is linked to the same thing as /boot/xen.gz
if [ "x$(readlink %sboot/xen.gz)" = "x$(readlink %sboot/xen-debug.gz)" ]
then
    # Remove the trailing '-d' in the filename stem
    NON_DEBUG_XEN=$(basename $(readlink %sboot/xen.gz) -d.gz).gz

# or if the symlink is from xen.gz to xen-debug.gz (as since CP-7811)
elif [ "x$(readlink %sboot/xen.gz)" = "xxen-debug.gz" ]
then
    NON_DEBUG_XEN=$(basename $(readlink %sboot/xen-debug.gz) -d.gz).gz
fi

if [ -n "${NON_DEBUG_XEN}" -a -e "%sboot/${NON_DEBUG_XEN}" ]
then
    rm -f %sboot/xen.gz
    ln -s ${NON_DEBUG_XEN} %sboot/xen.gz
fi
""" % (pathprefix, pathprefix, pathprefix, pathprefix, pathprefix, pathprefix, pathprefix, pathprefix)

    def assertNotRunningDebugXen(self):
        # Check that we're not using a debugging-enabled Xen by seeing if the "debug=y" flag is present
        if not self.execdom0("xl dmesg | fgrep \"Xen version\" | fgrep \"debug=y\"", retval = 'code'):
            raise xenrt.XRTFailure("Booted a debug=y Xen when FORCE_NON_DEBUG_XEN flag was present")

    def upgrade(self, newVersion=None, suppackcds=None):
        """Upgrade this host"""
        if not newVersion:
            newVersion = productVersionFromInputDir(xenrt.TEC().getInputDir())

        # Clear the CLI cache
        xenrt.lib.xenserver.cli.clearCacheFor(self.machine)
        # Set ourself as not tailored
        self.tailored = False
        # Create a new host object of the appropriate type
        newHost = xenrt.lib.xenserver.hostFactory(newVersion)(self.machine,
                                                              productVersion=newVersion)
        # Populate it with our information
        self.populateSubclass(newHost)
        # Call the private upgrade method
        newHost._upgrade(newVersion, suppackcds=suppackcds)
        newHost.checkVersion()
        # Set our replaced pointer
        self.replaced = newHost
        # Try and update the host object in the registry (if present)
        try:
            xenrt.TEC().registry.hostReplace(self, newHost)
        except Exception, e:
            xenrt.TEC().warning("Upgrade host replace failed: %s" % (str(e)))

        # Return the new host object
        return newHost

    def _upgrade(self, newVersion, suppackcds=None):
        # Upgrade to the current version
        self.install(upgrade=True, suppackcds=suppackcds)
       
        if not xenrt.TEC().lookup("OPTION_NO_AUTO_PATCH", False, boolean=True):
            # Wait to allow Xapi database to be written out
            xenrt.sleep(300)
            self.applyRequiredPatches()

    def applyWorkarounds(self):
        """Apply any workarounds to this host"""
        if xenrt.TEC().lookup("WORKAROUND_CC_SQUEEZED", False, boolean=True):
            xenrt.TEC().warning("Using CC squeezed workaround")
            self.execdom0("chkconfig squeezed on")
            self.execdom0("service squeezed start")
        if xenrt.TEC().lookup("WORKAROUND_CC_FWHTTP", False, boolean=True):
            xenrt.TEC().warning("Altering CC firewall")
            self.execdom0("iptables -I OUTPUT -p tcp --dport 80 -m state "
                          "--state NEW -d %s -j ACCEPT" %
                          (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")))
            self.iptablesSave()
        if xenrt.TEC().lookup("WORKAROUND_CA136054", False, boolean=True):
            xenrt.TEC().warning("Applying CA-136054 workaround")
            self.execdom0("mkdir -p /usr/lib/xen/bin")
            self.execdom0("ln -s /usr/lib64/xen/bin/vgpu /usr/lib/xen/bin/vgpu || true")

    def findUSBDevice(self):
        """Find the block device node corresponding to a USB flash device."""
        usbdevice = None
        scsidevices = string.split(self.execdom0("ls -d /sys/block/sd? 2>/dev/null | cat"))
        for d in scsidevices:
            d = os.path.basename(d)
            # Filter out any devices larger than 10GB
            size = int(self.execdom0("cat /sys/block/%s/size" % (d))) * 512
            if size > 10 * xenrt.GIGA:
                xenrt.TEC().logverbose("Device %s looks too big at %uMB to "
                                       "be a USB device" % (d, size/xenrt.MEGA))
                continue
            if size < 800 * xenrt.MEGA:
                xenrt.TEC().logverbose("Device %s looks too small at %uMB to "
                                       "be a USB device" % (d, size/xenrt.MEGA))
                continue
            t = string.strip(self.execdom0("cat /sys/block/%s/device/type" %
                                           (d)))
            if t == "0":
                r = string.strip(self.execdom0("cat /sys/block/%s/removable" %
                                               (d)))
                if r == "1":
                    usbdevice = "/dev/%s" % (d)
                    break
        return usbdevice

    def installComplete(self, handle, waitfor=False, upgrade=False):
        nfsdir, packdir, pxe, uefi = handle

        if waitfor:
            # Monitor for installation complete
            try:
                installTimeout = 1800 + int(self.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0"))
                
                # Start up a thread to ssh into the host installer
                pw = xenrt.TEC().lookup("TEST_INSTALLER_SSHPW", None)
                thread = None
                if pw is not None:
                    thread = SshInstallerThread(self, 1800, pw)
                    thread.start()
                    
                xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                                  installTimeout,
                                  desc="Installer boot on !%s" %
                                  (self.getName()))
                if thread is not None:
                    thread.stop()
            except xenrt.XRTException, e:
                if not re.search("timed out", e.reason):
                    raise e
                if thread is not None:
                    thread.stop()

                # Try again if this is a known BIOS/hardware boot problem
                if not self.checkForHardwareBootProblem(True):
                    # Reach here if no known boot problem was seen
                    
                    # If the host booted into a XenServer installation then
                    # it probably failed to PXE boot and this is an old
                    # install. If this is the case we'll retry once.
                    serlog = string.join(\
                        self.machine.getConsoleLogHistory()[-20:], "\n")
                    if "Your XenServer Host has now finished booting" in \
                           serlog:
                        xenrt.TEC().warning(\
                            "First attempt to install to %s timed out, host "
                            "may have failed to PXE boot, will retry" %
                            (self.getName()))
                    else:
                        raise e
                # Retry once by power cycling to (re)start the install
                test = False
                count = 0
                while test == False:
                    self.machine.powerctl.cycle()
                    try:
                        xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                                  installTimeout,
                                  desc="Installer boot on !%s" %
                                  (self.getName()))
                    except:
                        count += 1
                        if count == 10:
                            test = True
                    else:
                        test = True

            self.checkHostInstallReport("%s/.xenrtsuccess" % (nfsdir.path()))
            xenrt.TEC().progress("Installation complete, waiting for host "
                                 "boot.")

            # Boot the local disk  - we need to update this before the machine
            # reboots after setting the signal flag.
            if uefi:
                self.writeUefiLocalBoot(nfsdir, pxe)
            else:
                pxe.setDefault("local")
                pxe.writeOut(self.machine)
            if self.bootLun:
                pxe.writeISCSIConfig(self.machine, boot=True)
    
        # Wait for the machine to come up so we can SSH in. The sleep is
        # to avoid trying to SSH to the installer
        xenrt.sleep(30)
        try:
            self.waitForSSH(900, desc="Host boot (!%s)" % (self.getName()))
        except xenrt.XRTFailure, e:
            if not self.checkForHardwareBootProblem(True):
                raise
            # checkForHardwareBootProblem power cycled the machine, check again
            try:
                self.waitForSSH(900, desc="Host boot (!%s)" % (self.getName()))
            except xenrt.XRTFailure, e:
                self.checkForHardwareBootProblem(False)
                raise

        self.waitForFirstBootScriptsToComplete()

        if self.lookup("INSTALL_DISABLE_FC", False, boolean=True):
            self.enableAllFCPorts()

        # Make sure we don't leave this thing hanging around
        try:
            self.execdom0("mount LABEL=IHVCONFIG /mnt")
            self.execdom0("rm -f /mnt/xenrt-revert-to-factory")
            self.execdom0("umount /mnt")
        except:
            pass

        dom0cpus = xenrt.TEC().lookup("OPTION_XE_SMP_DOM0", None)
        if dom0cpus:
            if dom0cpus == "ALL":
                if not self.getMyVCPUs() == self.getCPUCores():
                    raise xenrt.XRTFailure("Not using all cpus in Domain-0.")
            else:
                if not int(dom0cpus) == self.getMyVCPUs():
                    raise xenrt.XRTFailure("Not using correct number " 
                                           "of cpus in Domain-0.")   
 
        # Clean up
        if packdir:
            packdir.remove()
        if nfsdir:
            nfsdir.remove()

        # Rio buld around 4.0.0b2-3674 appear to fail to run commands
        # executed early after boot. Sleep a bit.
        if xenrt.TEC().lookup("WORKAROUND_20070714", False, boolean=True):
            xenrt.sleep(600)

        if xenrt.TEC().lookup("OPTION_NFS_LOCAL", False, boolean=True):
            # Create a temporary NFS directory and mount it on /local.
            local = xenrt.NFSDirectory(keep=1) 
            self.execdom0("/etc/init.d/iptables stop")
            self.execdom0("mkdir -p /local")
            self.execdom0("echo %s /local nfs defaults 0 0 >> /etc/fstab" %
                          (local.getMountURL("")))
            self.execdom0("mount /local")
            self.execdom0("/etc/init.d/iptables start")

        # Tailor
        if not self.tailored:
            xenrt.TEC().progress("Tailoring the host")
            self.tailor()
            self.tailored = True

            # Allow xenagentd to dump core
            initd = ["xenagentd", "xend", "sshd"]
            for x in initd:
                if xenrt.TEC().lookup("OPTION_NOTWEAK_%s" % (x), False):
                    continue
                ifile = "/etc/init.d/%s" % (x)
                self.execdom0("if [ -e %s ]; then "
                              "  mv %s %s.orig; "
                              "  awk '{print;if(FNR==1)"
                              "   {print "
                              "     \"DAEMON_COREFILE_LIMIT=unlimited\"}}' "
                              "         < %s.orig >%s ; "
                              "  chmod 755 %s; "
                              "fi" %
                              (ifile, ifile, ifile, ifile, ifile, ifile))
                self.execdom0("if [ -e %s ]; then %s restart; fi" %
                              (ifile, ifile))
                xenrt.sleep(5)
            xenrt.sleep(20)
        
        # Enable guest console logging
        if xenrt.TEC().lookup("ENABLE_VM_CONSOLE_LOGS", True, boolean=True):
            try:
                self.enableGuestConsoleLogger(persist=True)
            except Exception, e:
                xenrt.TEC().warning("Exception while enabling guest console "
                "logger: " + str(e))

        xenrt.TEC().progress("Completed installation of XenServer host")

        if upgrade:
            # If this is a slave host, wait for it to have become enabled
            # (CA-32505)
            if self.pool and self.pool.master != self:
                self.waitForEnabled(300, desc="Wait for upgraded slave to "
                                              "become enabled")
            self.postUpgrade()

        if xenrt.TEC().lookup("OPTION_NO_DOM0_SWAP", False, boolean=True):
            xenrt.TEC().warning("Disabling dom0 swap")
            self.execdom0("/sbin/swapoff -a")
            self.execdom0("echo '/sbin/swapoff -a' >> /etc/rc.local")

        if xenrt.TEC().lookup("POSTINSTALL_WAIT_XAPI", False, boolean=True):
            xenrt.TEC().logverbose("Waiting for Xapi post host install...")
            self.waitForXapi(600, desc="Xapi response after host install")

        if xenrt.TEC().lookup("HOST_ENFORCE_CC_RESTRICTIONS", False):
            self.enableCC()

        if xenrt.TEC().lookup("USE_BLKTAP2", False):
            self.execdom0("sed -i 's/default-vbd-backend-kind=vbd3/default-vbd-backend-kind=vbd/' /etc/xenopsd.conf")
            self.restartToolstack()

        if xenrt.TEC().lookup("USE_TLS_" + (self.productVersion or "").upper(), False, boolean=True):
            self.execdom0("sed -i 's/TIMEOUTclose = 0/options = NO_SSLv3\\\nTIMEOUTclose = 0/g' /etc/init.d/xapissl", newlineok=True)
            self.execdom0("cat /etc/init.d/xapissl")
            self.restartToolstack()
        
        if xenrt.TEC().lookup("HOST_POST_INSTALL_REBOOT", False, boolean=True):
            self.reboot()

        optionRootMpath = self.lookup("OPTION_ROOT_MPATH", None)
        if optionRootMpath != None and len(optionRootMpath) > 0:
            # Check to ensure that there is a multipath topology if we did multipath boot.
            if not len(self.getMultipathInfo()) > 0 :
                raise xenrt.XRTFailure("There is no multipath topology found with multipath boot")

        syslogfmt = xenrt.TEC().lookup("DOM0_SYSLOG_FORMAT", None)
        if syslogfmt:
            self.changeSyslogFormat(syslogfmt)

    def waitForFirstBootScriptsToComplete(self):
        ret = ""
        maxLoops = 10 # By default wait 5 minutes (each loop has a 30s sleep)
        try:
            # Check if we have a large disk, as in that situation we will need to allow more time (CA-165064)
            disk = self.getInventoryItem("PRIMARY_DISK")
            fdiskout = self.execdom0("fdisk -l %s" % disk)
            disksize = None
            for line in fdiskout.splitlines():
                matches = re.search("Disk %s: (.*) GB" % disk, line)
                if matches != None:
                    disksize = int(round(float(matches.group(1))))
                    break
            if disksize and disksize > 500:
                # Allow an extra loop per 100GB
                maxLoops += ((disksize-500) / 100)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception while attempting to determine disk size: %s" % str(e))
        for i in range(maxLoops):
            ret = self.execdom0("cat /etc/firstboot.d/state/99-remove-firstboot-flag || true").strip()
            if "success" in ret:
                xenrt.TEC().logverbose("First boot scripts completed: %s" % ret)
                return
            else:
                xenrt.sleep(30)

        xenrt.TEC().logverbose("First boot scripts didn't complete")

    def checkHostInstallReport(self, filename):
        """Checks a host installer completion file. If the file is not
        empty the install/upgrade will be assumed to have failed and the
        contents of the file is /tmp/install.log in the installer."""
        try:
            f = file(filename, "r")
        except:
            raise xenrt.XRTError("Could not retrieve .xenrtsuccess for machine !%s" % self.getName())
        data = f.read()
        f.close()
        if data != "":
            f = file("%s/install-%s.log" % (xenrt.TEC().getLogdir(),
                                            self.getName()),
                     "w")
            f.write(data)
            f.close()

            # See if we've got a support.tar.bz2 as well
            slog = "%s/support.tar.bz2" % (os.path.dirname(filename))
            if os.path.exists(slog):
                shutil.copy(slog, "%s/support-%s.tar.bz2" % (xenrt.TEC().getLogdir(),
                                                             self.getName()))

            r = re.search(r"INSTALL FAILED.*^(\w+:.*)",
                          data,
                          re.MULTILINE|re.DOTALL)
            if r:
                reason = r.group(1).split("\n")[0]
            else:
                if "INSTALL FAILED" in data:
                    if "in removeBlockingVGs" in data:
                        reason = "failure in removeBlockingVGs"
                    elif "in inspectTargetDisk" in data:
                        reason = "failure in inspectTargetDisk"
                    else:
                        reason = "INSTALL FAILED"
                else:
                    reason = "unknown failure"

            if reason.strip() == "IOError: [Errno 5] Input/output error":
                # Detect CA-45037 errors and don't report the specific machine
                raise xenrt.XRTFailure("CA-45037 I/O error while installing build via NFS")

            raise xenrt.XRTFailure("Installation failed on !%s: %s" %
                                   (self.getName(), reason.decode("ascii", "ignore")))

    def getLocalDisks(self):
        # A local disk must have:
        #    - /sys/block/<dev>/removable = "0"
        #    - /sys/block/<dev>/device/vendor != "DGC"
        devs = string.split(self.execdom0('ls /sys/block | '
                                          'grep "^[sh]d[a-p]" | cat'))
        devs.extend(string.split(self.execdom0('ls /sys/block | grep "^cciss"'
                                               ' | cat')))
        localdisks = []
        for d in devs:
            r = int(self.execdom0("cat /sys/block/%s/removable" % (d)))
            try:
                v = string.strip(self.execdom0(\
                        "cat /sys/block/%s/device/vendor" % (d)))
            except:
                v = "unknown"
            if (r == 0 and v != "DGC") or (v == "ServeRA"):
                if d[0] == "s":
                    localdisks.append("/dev/%s" % (d))
                elif d[0:5] == "cciss":
                    localdisks.append("/dev/%s" %
                                      (string.replace(d, "!", "/")))

        return localdisks

    def getLocalDiskSizes(self):
        """Returns the local disk sizes in bytes as a dictionary disk->size"""
        disksizes = {}
        localdisks = self.getLocalDisks()
        xenrt.TEC().logverbose("Getting disk sizes for %s" %
                               (str(localdisks)))
        #get the local disk size using gdisk
        for ld in localdisks:
            size = self.execdom0("gdisk -l %s | awk 'BEGIN{sectors=0;sector_size=0;}" \
                                "{if ($0~/Disk .* sectors/) sectors=$3; if ($0~/Logical sector size.*/) sector_size=$4;}" \
                                "END{print sectors*sector_size}'" % (ld))
            #disksize in bytes may come in as exponential numbers, so we need to convert to float first
            disksizes[ld] = int(float(size.strip()))
        return disksizes

    def cleanLocalDisks(self):
        """Blank the partition tables of local disks."""
        # Blank the partition tables of any fixed disks so that the
        # product will install SRs on them.
        localdisks = self.getLocalDisks()
        xenrt.TEC().logverbose("Blanking partition tables on %s" %
                               (str(localdisks)))
        for ld in localdisks:
            try:
                self.execdom0("test -x /opt/xensource/bin/diskprep && /opt/xensource/bin/diskprep -f %s || dd if=/dev/zero of=%s bs=4096 count=10" % (ld, ld))
                self.execdom0('echo -e "0,100,0xDE,*" | /sbin/sfdisk '
                              '--no-reread  -uM %s' % (ld))
                if xenrt.TEC().lookup("OPTION_NO_DISK_CLAIM",
                                      False,
                                      boolean=True):
                    self.execdom0('echo -e "0,100,0x83,*" | /sbin/sfdisk '
                                  '--no-reread  -uM %s' % (ld))
            except Exception, e:
                xenrt.TEC().logverbose("Exception cleaning disk %s: %s" %
                                       (ld, str(e)))
        self.execdom0("sync")

    def installHostSupPacks(self, isoPath, isoName, reboot=True):

        #Download ISO file form DISTFILES path
        hostISOURL = "%s/%s" %(isoPath, isoName)
        hostISO = xenrt.TEC().getFile(hostISOURL)
        if not hostISO: 
            raise xenrt.XRTError("Failed to fetch host supppack ISO.")

        xenrt.checkFileExists(hostISO, level=xenrt.RC_FAIL)

        hostPath = "/tmp/%s" % (isoName)

        sh = self.sftpClient()
        try:
            sh.copyTo(hostISO, hostPath)
        finally:
            sh.close()

        #Installing suppack
        xenrt.TEC().logverbose("Installing Host Supplemental pack: %s" % isoName)
        self.execdom0("xe-install-supplemental-pack %s" % hostPath)
        if reboot:
            self.reboot()

    def applyRequiredPatches(self, applyGuidance=True, applyGuidanceAfterEachPatch=False):
        """Apply suitable patches from the list given by the user.
        Returns True if any patches were applied."""
        reply = False
        applyGuidanceAfterEachPatch = applyGuidance and applyGuidanceAfterEachPatch
        existingGuidanceList = self.minimalList("patch-list params=after-apply-guidance hosts:contains=%s" % self.uuid)
        
        xenrt.TEC().logverbose("Applying required hotfixes. Product-version: %s" % self.productVersion)
        if xenrt.TEC().lookup("APPLY_ALL_RELEASED_HFXS", False, boolean=True):
            if xenrt.TEC().isReleasedBuild():
                xenrt.TEC().logverbose("This is a release build. Adding released hotfixes to config.")
                xenrt.TEC().config.addAllHotfixes()
            else:
                xenrt.TEC().logverbose("This is not a release build. Not adding released hotfixes to config.")
        else:
            targetHotfix = xenrt.TEC().lookup("TARGET_HOTFIX", None)
            if targetHotfix:
                """Build a list of hotfixes that need to be installed to patch the host upto the targetHotfix"""

                # Look up for available hotfixes from XenRT's hotfix list.
                hfxDict = xenrt.TEC().lookup(["HOTFIXES", self.productVersion])
                xenrt.TEC().logverbose("HFX dictionary for %s: %s" % (self.productVersion, hfxDict))

                branch = None
                for b in hfxDict.keys():
                    if targetHotfix in hfxDict[b].keys():
                        branch = b
                if not branch:
                    raise xenrt.XRTFailure("Could not find hotfix '%s' in hotfix dict: '%s'" % (targetHotfix, hfxDict))

                hotfixPaths = []
                for hotfixKey, hotfixPath in sorted(hfxDict[branch].iteritems()):
                    if hotfixKey <= targetHotfix:
                        hotfixPaths.append(hotfixPath)

                for hf in hotfixPaths:
                    self.applyPatch(xenrt.TEC().getFile(hf))

        # CARBON_PATCHES contains any patches to be applied regardless of the
        # product version being installed. It is either a comma separated
        # list of patch paths or a tree of variables of patch paths.
        patches = xenrt.TEC().lookupLeaves("CARBON_PATCHES")
        if len(patches) == 1:
            # Possibly legacy use with a comma-separated list
            patches = string.split(patches[0], ",")
        # Repeat with CPATCHES
        cpatches = xenrt.TEC().lookupLeaves("CPATCHES")
        if len(cpatches) == 1:
            # Possibly legacy use with a comma-separated list
            cpatches = string.split(cpatches[0], ",")
        patches.extend(cpatches)

        # CARBON_PATCHES_<version> (where <version> is upper case) is a
        # per-version set of patches using the same syntax as CARBON_PATCHES
        vpatches = xenrt.TEC().lookupLeaves("CARBON_PATCHES_%s" % self.productVersion.upper())
        if len(vpatches) == 1:
            # Possibly legacy use with a comma-separated list
            vpatches = string.split(vpatches[0], ",")
        patches.extend(vpatches)
        # Repeat with CPATCHES_<version>
        cvpatches = xenrt.TEC().lookupLeaves("CPATCHES_%s" % self.productVersion.upper())
        if len(cvpatches) == 1:
            # Possibly legacy use with a comma-separated list
            cvpatches = string.split(cvpatches[0], ",")
        patches.extend(cvpatches)

        if patches and xenrt.TEC().lookup("CHECK_DUPLICATE_HOTFIX", False, boolean=True):
            patches = self.getUniquePatches(patches)

        #Install internal RPU hotfix, if any
        if xenrt.TEC().lookup("INSTALL_RPU_HOTFIX", False, boolean=True):
            rpuPatch = xenrt.TEC().lookup(["VERSION_CONFIG",self.productVersion,"INTERNAL_RPU_HOTFIX"])
            if rpuPatch:
                patches.extend([xenrt.TEC().lookup("INPUTDIR") + "/xe-phase-1/%s" % rpuPatch])

        # Apply all the patches we found
        for patch in [x for x in patches if x != "None"]:
            patchFile = xenrt.TEC().getFile(patch)
            if patchFile:
                self.applyPatch(patchFile, applyGuidance=applyGuidanceAfterEachPatch)
                reply = True
            else:
                raise xenrt.XRTFailure("Error: Failed to retrieve %s" % (patch))
        
        # Perform most significant apply action
        if applyGuidance and not applyGuidanceAfterEachPatch:
            guidanceList = self.minimalList("patch-list params=after-apply-guidance hosts:contains=%s" % self.uuid)
            guidance = [guide for guide in set(guidanceList) if guide and guidanceList.count(guide)>existingGuidanceList.count(guide) ]
            self.applyGuidance( guidance)

        supptarballs = xenrt.TEC().lookup("POST_HFX_SUPP_PACK_TGZS", None)
        if supptarballs:
            for supptar in supptarballs.split(","):
                tarball = xenrt.TEC().getFile(supptar)
                if not tarball:
                    tarball = xenrt.TEC().getFile("xe-phase-1/%s" % (supptar))
                if not tarball:
                    tarball = xenrt.TEC().getFile("xe-phase-2/%s" % (supptar))
                if not tarball:
                    raise xenrt.XRTError("Couldn't find %s." % (supptar))
                xenrt.TEC().comment("Using supplemental pack tarball %s." % (tarball))
                tdir = xenrt.TEC().tempDir()
                xenrt.util.command("tar -zxf %s -C %s" % (tarball, tdir))
                iso = glob.glob("%s/*.iso" % tdir)[0]
                isoname = os.path.basename(iso)
                sftp = self.sftpClient()
                sftp.copyTo(iso, "/tmp/%s" % isoname)
                sftp.close()
                self.execdom0("cd /tmp; xe-install-supplemental-pack %s" % isoname)
                self.execdom0("rm -f /tmp/%s" % isoname)
            self.reboot()

        # Before we upgrade any RPMs, record the last-modified-time of /boot/xen.gz
        # We'll use this to check whether any of the RPMs touched it.
        xenLastModified = self.execdom0("stat /boot/xen.gz | grep ^Modify")

        # Apply any upgraded RPMs. CARBON_RPM_UPDATES contains any
        # RPMs to be applied regardless of the product version being
        # installed. It is either a comma separated list of update paths
        # or a tree of variables of update paths.
        rpms = xenrt.TEC().lookupLeaves("CARBON_RPM_UPDATES")
        if len(rpms) == 1:
            # Possibly legacy use with a comma-separated list
            rpms = string.split(rpms[0], ",")

        # RPM_UPDATES_<version> (where <version> is upper case) is a
        # per-version set of updates using the same syntax as
        # CARBON_RPM_UPDATES
        vrpms = xenrt.TEC().lookupLeaves("RPM_UPDATES_%s" % self.productVersion.upper())
        if len(vrpms) == 1:
            # Possibly legacy use with a comma-separated list
            vrpms = string.split(vrpms[0], ",")
        rpms.extend(vrpms)

        remotenames = []
        for rpm in [x for x in rpms if x != "None"]:
            rpmfile = xenrt.TEC().getFile(rpm)
            remotefn = "/tmp/%s" % os.path.basename(rpm)
            sftp = self.sftpClient()
            try:
                sftp.copyTo(rpmfile, remotefn)
            finally:
                sftp.close()
            remotenames.append(remotefn)
        if len(remotenames) > 0:
            force = xenrt.TEC().lookup("FORCE_RPM_UPDATES", False,boolean=True)
            if force:
                self.execdom0("rpm --upgrade -v --force --nodeps %s" % (string.join(remotenames)))
            else:
                self.execdom0("rpm --upgrade -v %s" % (string.join(remotenames)))
            self.reboot()
            reply = True

        if xenrt.TEC().lookup("OPTION_TEMP_SCTX_1660", False, boolean=True) and isinstance(self, xenrt.lib.xenserver.ClearwaterHost):
            xenrt.TEC().logverbose('Using OPTION_TEMP_SCTX_1660')
            rpmSource = ['http://files.uk.xensource.com/usr/groups/xenrt/sctx1660/kernel-kdump-2.6.32.43-0.4.1.xs1.8.0.845.170786.i686.rpm',
                         'http://files.uk.xensource.com/usr/groups/xenrt/sctx1660/openvswitch-modules-kdump-2.6.32.43-0.4.1.xs1.8.0.845.170786-1.4.6-141.9924.i386.rpm',
                         'http://files.uk.xensource.com/usr/groups/xenrt/sctx1660/kernel-xen-2.6.32.43-0.4.1.xs1.8.0.845.170786.i686.rpm',
                         'http://files.uk.xensource.com/usr/groups/xenrt/sctx1660/openvswitch-modules-xen-2.6.32.43-0.4.1.xs1.8.0.845.170786-1.4.6-141.9924.i386.rpm']
            self.execdom0('mkdir /tmp/sctx1660')
            for rpm in rpmSource:
                self.execdom0('wget %s -P /tmp/sctx1660' % (rpm))
            self.execdom0('rpm -ivh /tmp/sctx1660/*.rpm')
            self.reboot()

        # After the official CARBON_XXX_UPDATES, a chance to apply any customized updates.
        updatesList = []
        for key in ['CUSTOM_UPDATES_' + self.productVersion.upper(), 'CST_UPD_' + self.productVersion.upper(), 'CST_URL_' + self.productVersion.upper(), 'CST_URL2_' + self.productVersion.upper(), 'CUSTOM_UPDATES']:
            updates = xenrt.TEC().lookup(key, None)
            if updates:
                updatesList.extend(string.split(updates, ","))
        
        if len(updatesList) > 0:
            remoteupdates = []
            for u in updatesList:
                uf = xenrt.TEC().tempFile()
                if u.startswith("http:"):
                    xenrt.command("wget '%s' -O '%s'" % (u, uf))
                else:
                    data = xenrt.GEC().dbconnect.jobDownload(u)
                    fd = file(uf, "wb")
                    fd.write(data)
                    fd.close()
                
                remoteuf = "/tmp/%s" % os.path.basename(u)
                sftp = self.sftpClient()
                try:
                    sftp.copyTo(uf, remoteuf)
                finally:
                    sftp.close()
                remoteupdates.append(remoteuf)
            
            rpms = []
            for u in remoteupdates:
                if u.endswith(".rpm"):
                    rpms.append(u)
            if len(rpms) > 0:
                self.execdom0("rpm --upgrade -v --force %s" % string.join(rpms, " "))
            
            for u in remoteupdates:
                if not u.endswith(".rpm"):
                    if u.endswith(".tar") : options = "xvf"
                    elif u.endswith(".tgz") or u.endswith(".tar.gz"): options = "xvzf"
                    elif u.endswith(".tbz") or u.endswith(".tar.bz2"): options = "xvjf"
                    else:
                        raise xenrt.XRTError("CUSTOM_UPDATES %s doesn't look like a rpm or a "
                                             "(maybe compressed) tarball. Suffix must be one of "
                                             "tar/tar.gz/tgz/tar.bz2/tbz." % os.path.basename(u))
                    self.execdom0("cd / && tar %s %s -C / --backup=simple --suffix=.orig"
                                  % (options, u))
            # An extra xapi restart is sometimes wanted before host reboot
            self.execdom0("/opt/xensource/bin/xe-toolstack-restart")
            self.reboot()
            reply = True
            
        # Now see whether /boot/xen.gz was touched by those updates
        xenLastModifiedNew = self.execdom0("stat /boot/xen.gz | grep ^Modify")
        if xenLastModified <> xenLastModifiedNew and xenrt.TEC().lookup("FORCE_NON_DEBUG_XEN", None):
            # It looks like the RPM upgrades touched Xen, so we need to ensure that we're using the non-debug version.
            self.execdom0(self.swizzleSymlinksToUseNonDebugXen(pathprefix="/"))
            self.reboot()
            self.assertNotRunningDebugXen()

        # Update our product version in case the hotfix has changed it
        self.checkVersion()

        return reply

    
    def checkNetworkInterfaceConfig(self, name, proto, ip, netmask, gateway):
        #CHECKME: Need checks for IPv6 configs
        ok = 1
        try:
            config = self.getNetworkInterfaceConfig(name)
        except xenrt.XRTError, e:
            ok = 0
            xenrt.TEC().reason(str(e))
            config = None

        if config:
            if not config.has_key("BOOTPROTO"):
                ok = 0
                xenrt.TEC().reason("Config file for %s does not specify "
                                   "BOOTPROTO" % (name))
            else:
                if proto == "static" and config["BOOTPROTO"] == "none":
                    pass
                elif proto != config["BOOTPROTO"]:
                    ok = 0
                    xenrt.TEC().reason("Config file for %s has "
                                       "BOOTPROTO=%s (expected %s)" %
                                       (name, config["BOOTPROTO"], proto))
            if proto == "static":
                if not config.has_key("IPADDR"):
                    ok = 0
                    xenrt.TEC().reason("Config file for %s does not "
                                       "specify IPADDR" % (name))
                elif ip != config["IPADDR"]:
                    ok = 0
                    xenrt.TEC().reason("Config file for %s has "
                                       "IPADDR=%s (expected %s)" %
                                       (name, config["IPADDR"], ip))
                if not config.has_key("NETMASK"):
                    ok = 0
                    xenrt.TEC().reason("Config file for %s does not "
                                       "specify NETMASK" % (name))
                elif netmask != config["NETMASK"]:
                    ok = 0
                    xenrt.TEC().reason("Config file for %s has "
                                       "NETMASK=%s (expected %s)" %
                                       (name, config["NETMASK"], netmask))
                if not config.has_key("GATEWAY"):
                    ok = 0
                    xenrt.TEC().reason("Config file for %s does not "
                                       "specify GATEWAY" % (name))
                elif gateway != config["GATEWAY"]:
                    ok = 0
                    xenrt.TEC().reason("Config file for %s has "
                                       "GATEWAY=%s (expected %s)" %
                                       (name, config["GATEWAY"], ip))
        return ok

    def check(self,
              cd=None,
              primarydisk=None,
              guestdisks=None,
              source=None,
              timezone=None,
              interfaces=None,
              ntpserver=None,
              nameserver=None,
              hostname=None): 
        """Check an installed host has the correct configuration."""
        if xenrt.TEC().lookup("OPTION_NO_HOST_CHECK", False, boolean=True):
            return

        # If an optional argument is not given use the value we stored
        # previously. If that is None then use a default.
        if not cd:
            cd = self.i_cd
        if not primarydisk:
            primarydisk = self.i_primarydisk
        if not primarydisk:
            primarydisk = "sda"
        if not guestdisks:
            guestdisks = self.i_guestdisks
        if not guestdisks:
            guestdisks = ["sda"]
        if not source:
            source = self.i_source
        if not source:
            source = "url"
        if not timezone:
            timezone = self.i_timezone
        if not timezone:
            timezone = "UTC"
        if not interfaces:
            interfaces = self.i_interfaces
        if not interfaces:
            interfaces = [(None, "yes", "dhcp", None, None, None, None, None, None)]
        if not ntpserver:
            ntpserver = self.i_ntpserver
        if not nameserver:
            nameserver = self.i_nameserver
        if not hostname:
            hostname = self.i_hostname

        ok = 1
        
        # Guest disks
        if self.productVersion == "Rio":
            try:
                localSR = self.getSRs("lvm", local=True)[0]
                pbd = self.minimalList("pbd-list",args="sr-uuid=%s" % 
                                                  (localSR))[0]
                devices = self.genParamGet("pbd", pbd, "device-config", 
                                           "device")
                actual = []
                for dev in string.split(devices,","):
                    r = re.search(r"^/dev/(\w+)\d", dev)
                    if r:
                        actual.append(r.group(1))
                    r = re.search(r"^/dev/(\S+)p\d", dev)
                    if r:
                        actual.append(r.group(1))
                actual = string.join(actual)
                target = string.join(guestdisks)
                if actual != target:
                    ok = 0
                    xenrt.TEC().reason("Guest disk set is not %s (%s)" %
                                       (target, actual))
                else:
                    xenrt.TEC().logverbose("Guest disks are %s" % (actual))
                    # Confirm that DEFAULT_SR_PHYSDEVS matches the actual disks
                    pds = self.execdom0(". /etc/xensource-inventory && "
                                        "echo $DEFAULT_SR_PHYSDEVS")
                    pds = string.split(pds)
                    devices = string.split(devices,",")
                    pds.sort()
                    devices.sort()
                    if string.join(pds) != string.join(devices):
                        ok = 0
                        xenrt.TEC().reason("DEFAULT_SR_PHSYDEVS (%s) does not "
                                           "match PBD (%s)" % 
                                        (string.join(pds),string.join(devices)))
                    
            except Exception, e:
                if len(guestdisks) > 1:
                    ok = 0
                    xenrt.TEC().reason("Exception while verifying guest "
                                       "disks: " + str(e))

        # Timezone
        if self.execdom0("diff /etc/localtime /usr/share/zoneinfo/%s" %
                         (timezone), retval="code") != 0:
            ok = 0
            xenrt.TEC().reason("Timezone is not %s" % (timezone))
        else:
            xenrt.TEC().logverbose("Timezone is %s" % (timezone))

        # Interfaces
        for i in interfaces:
            name, enabled, proto, ip, netmask, gateway, protov6, ip6, gw6 = i
            if not name:
                name = self.getDefaultInterface()

            if self.checkNetworkInterfaceConfig(name, proto, ip, netmask, gateway) == 0:
                ok = 0

        # Hostname
        if hostname:
            actual = self.execdom0("hostname")
            actual = string.strip(actual)
            if not re.match(r'%s(-NIC\d+)?$' % (hostname,), actual):
                ok = 0
                xenrt.TEC().reason("Actual hostname % differs from %s" %
                                   (actual, hostname))
            else:
                xenrt.TEC().logverbose("Hostname is %s" % (actual))

        # Nameserver
        if nameserver:
            if self.execdom0("grep -q '%s' /etc/resolv.conf" %
                             (nameserver),
                             retval="code") != 0:
                ok = 0
                xenrt.TEC().reason("Nameserver %s not found in "
                                   "/etc/resolv.conf" % (nameserver))
            else:
                xenrt.TEC().logverbose("Nameserver %s found in /etc/resolv.conf" %
                                       (nameserver))

        # NTP Server
        if ntpserver:
            if self.execdom0("grep -q '%s' /etc/ntp.conf" % (ntpserver),
                             retval="code") != 0:
                if self.execdom0("grep -q '%s' /etc/ntp.conf.predhclient" % 
                                 (ntpserver),retval="code") != 0:
                    ok = 0
                    xenrt.TEC().reason("NTP server %s not in /etc/ntp.conf or"
                                       "/etc/ntp.conf.predhclient" % 
                                       (ntpserver))
                else:
                    xenrt.TEC().logverbose("NTP server %s found in "
                                           "/etc/ntp.conf.predhclient" % 
                                           (ntpserver))
            else:
                xenrt.TEC().logverbose("NTP server %s found in /etc/ntp.conf" %
                                       (ntpserver))

        # Per-version checks
        try:
            self.checkVersionSpecific()
        except:
            ok = 0

        # if the installer was run manually then we don't expect
        # the host config to match the install config.
        if xenrt.TEC().lookup("OPTION_NO_ANSWERFILE", False, boolean=True):
            return
        
        if ok == 0:
            raise xenrt.XRTFailure("Installed host configuration did not " +
                                   "match install configuration.")

    def cloneTemplate(self, template):
        templateuuid = self.parseListForUUID("template-list",
                                             "name-label",
                                              template)
    
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (templateuuid))
        args.append("new-name-label=%s" % (xenrt.randomGuestName()))
        return cli.execute("vm-clone", string.join(args)).strip()

    def getInventoryItem(self, param):
        """Look up a variable in /etc/xensource-inventory"""
        data = self.execdom0("grep ^%s= /etc/xensource-inventory | cat" %
                             (param))
        r = re.search("%s='(.+)'" % (param), data)
        if not r:
            raise xenrt.XRTError("No parameter '%s' found in "
                                 "/etc/xensource-inventory" % (param))
        return r.group(1)

    def getXenCaps(self):
        """Return a list of Xen capabilities"""
        caps = string.split(self.getHostParam("capabilities"))
        return map(lambda x:string.strip(x, ";"), caps)

    def getDomid(self, guest):
        """Return the domid of the specified guest."""
        # Look up the UUID of the guest
        uuid = guest.getUUID()
        domains = self.listDomains(includeS=True)
        if domains.has_key(uuid):
            return domains[uuid][0]
        raise xenrt.XRTError("Domain '%s' not found" % (uuid))

    def installIperf(self, version=""):
        """Installs the iperf application on the host"""
        if self.execdom0("test -f /usr/bin/iperf", retval="code") != 0:
            # Add a proxy if we know about one
            proxy = xenrt.TEC().lookup("HTTP_PROXY", None)
            if proxy:
                self.execdom0("sed -i '/proxy/d' /etc/yum.conf")
                self.execdom0("echo 'proxy=http://%s' >> /etc/yum.conf" % proxy)
            self.execdom0("yum --disablerepo=citrix --enablerepo=base,updates,extras install -y  gcc-c++")
            self.execdom0("yum --disablerepo=citrix --enablerepo=base install -y make")
            xenrt.objects.GenericPlace.installIperf(self, version)

    def createVBridge(self, name, vlan=None, autoadd=False, nic="eth0",
                      desc=None):
        """Create a new vbridge on the host"""
        cli = self.getCLIInstance()
        args = []
        args.append("vbridge-name=%s" % (name))
        if autoadd:
            args.append("auto-vm-add=true")
        else:
            args.append("auto-vm-add=false")
        if vlan != None:
            args.append("vbridge-vlan=%u" % (vlan))
            args.append("vbridge-nic=%s" % (nic))
        if desc:
            args.append("vbridge-description='%s'" % (desc))
        cli.execute("host-vbridge-add", string.join(args))

    def removeVBridge(self, name):
        """Remove a vbridge"""
        cli = self.getCLIInstance()
        args = []
        args.append("vbridge-name=%s" % (name))
        cli.execute("host-vbridge-remove", string.join(args))
        
    def getVBridges(self):
        """Return a dictionary of vbridges on the system."""
        reply = {}
        cli = self.getCLIInstance()
        data = cli.execute("host-vbridge-list")
        found = False
        h_name = None
        h_desc = None
        h_nic = None
        h_vlan = None
        h_autoadd = None
        re_title = re.compile(r"Virtual bridge: (\S+)")
        re_desc = re.compile(r"Description: (.*)$")
        re_nic = re.compile(r"NIC: (\S+)$")
        re_vlan = re.compile(r"VLAN: (\d+)$")
        re_autoadd = re.compile(r"Auto add to VM: (\w+)$")
        for line in string.split(data, "\n"):
            r = re_title.search(line)
            if r:
                if found and h_name:
                    reply[h_name] = (h_desc, h_nic, h_vlan, h_autoadd)
                h_name = r.group(1)
                found = True
                h_desc = None
                h_nic = None
                h_vlan = None
                h_autoadd = None
            r = re_desc.search(line)
            if r:
                h_desc = r.group(1)
            r = re_nic.search(line)
            if r:
                h_nic = r.group(1)
            r = re_vlan.search(line)
            if r:
                h_vlan = r.group(1)
            r = re_autoadd.search(line)
            if r:
                h_autoadd = r.group(1)
        if found and h_name:
            reply[h_name] = (h_desc, h_nic, h_vlan, h_autoadd)
        return reply

    def checkVBridge(self, name, vlan=None, autoadd=False, nic="eth0",
                     desc="(null)"):
        """Check vbridge has been installed correctly"""
        brs = self.getVBridges()
        if not brs.has_key(name):
            raise xenrt.XRTFailure("Could not find vbridge %s" % (name))
        h_desc, h_nic, h_vlan, h_autoadd = brs[name]
        if desc != h_desc:
            raise xenrt.XRTFailure("Description mismatch '%s' != '%s'" %
                                   (desc, h_desc))
        if autoadd and h_autoadd != "true":
            raise xenrt.XRTFailure("Auto VM add mismatch %s != %s" %
                                   (`autoadd`, h_autoadd))
        if vlan != None:
            if int(h_vlan) != vlan:
                raise xenrt.XRTFailure("VLAN mismatch %u != %u" %
                                       (vlan, int(h_vlan)))
            if nic != h_nic:
                raise xenrt.XRTFailure("NIC mismatch %s != %s" % (nic, h_nic))

        # Check the bridge actually exists
        ifs = self.getBridgeInterfaces(name)
        if not ifs:
            raise xenrt.XRTFailure("Bridge %s does not exist on the host" %
                                   (name))

        if vlan != None:
            vlanif = "%s.%u" % (nic, vlan)
            
            # Check we're attached to the right NIC
            if not vlanif in ifs:
                raise xenrt.XRTFailure("Bridge %s does not include %s" %
                                       (name, vlanif))
            
            # Check the VLAN interface exists
            try:
                self.execdom0("ifconfig %s" % (vlanif))
            except:
                raise xenrt.XRTFailure("Interface %s does not exist" %
                                       (vlanif))
            try:
                self.execdom0("ls /proc/net/vlan/%s" % (vlanif))
            except:
                raise xenrt.XRTFailure("%s does not exist in /proc/net/vlan" %
                                       (vlanif))

    def compatCLI(self):
        """Return if this host uses the compat mode CLI"""
        if self.lookup("OPTION_CLI_COMPAT", False, boolean=True) or \
               self.compat:
            return CLI_LEGACY_COMPAT
        return CLI_NATIVE

    def chooseTemplate(self, guesttype):
        """Choose a template name for installing a guest of this type"""
        # Try a per-version template name first and fall back to a global
        template = self.lookup(guesttype, None)
        if not template:
            raise xenrt.XRTError("Could not identify a suitable template for "
                                 "%s" % (guesttype))

        # See if we have a choice
        choices = string.split(template, ",")
        if len(choices) == 1:
            return choices[0]
        xenrt.TEC().logverbose("Choices for %s: %s" % (guesttype, template))
        if not self.templates:
            self.updateTemplates()
        if not self.templates:
            # shouldn't happen
            return choices[0]
        for choice in choices:
            if choice in self.templates:
                return choice
        raise xenrt.XRTError("Could not find one of %s in %s" %
                             (choices, string.join(self.templates, ",")))

    def createGenericLinuxGuest(self,
                                name=None,
                                arch=None,
                                start=True,
                                sr=None,
                                bridge=None,
                                vcpus=None,
                                memory=None,
                                allowUpdateKernel=True,
                                disksize=None,
                                use_ipv6=False,
                                generic_distro=None,
                                rawHBAVDIs=None):
        """Installs a generic Linux VM for non-OS-specific tests."""

        if not name:
            name = xenrt.randomGuestName(distro="genericlin", arch=arch)

        if arch != None and arch.endswith("64"):
            distro = self.lookup("GENERIC_LINUX_OS_64", "centos53")
            t = self.createBasicGuest(distro, vcpus=vcpus, memory=memory,name=name, arch=arch, 
                                      use_ipv6=use_ipv6, bridge=bridge, disksize=disksize, sr=sr)
            if not start:
                t.shutdown()
            return t

        if not generic_distro:
            # Just to make sure that GENERIC_LINUX_OS config is synchronous with
            # our ad-hoc 32bit OS choice here
            generic_distro = self.lookup("GENERIC_LINUX_OS", "etch") 
            xenrt.TEC().logverbose("GENERIC_LINUX_OS lookup is %s" % (generic_distro))
        if generic_distro != "etch":
            xenrt.TEC().logverbose("Create basic guest")
            t = self.createBasicGuest(generic_distro, vcpus=vcpus, memory=memory,name=name, 
                                      use_ipv6=use_ipv6, bridge=bridge, disksize=disksize, sr=sr)
            if not start:
                t.shutdown()
            return t
        else:
            xenrt.TEC().logverbose("Template is %s" % (self.getTemplate("debian")))
            t = self.guestFactory()(\
                name,
                self.getTemplate("debian"),
                self,
                password=xenrt.TEC().lookup("ROOT_PASSWORD_DEBIAN"))
            # Install from Debian template
            xenrt.TEC().logverbose("Install from Debian template")
            if disksize == None:
                disksize = t.DEFAULT
            if vcpus != None:
                t.setVCPUs(vcpus)
            if memory != None:
                t.setMemory(memory)
            if bridge:
                vifs = [("eth0", bridge, xenrt.randomMAC(), None)]
                t.install(self,
                          distro="debian",
                          start=start,
                          sr=sr,
                          vifs=vifs,
                          rootdisk=disksize,
                          use_ipv6=use_ipv6,
                          rawHBAVDIs=rawHBAVDIs)
            else:
                t.install(self,
                          distro="debian",
                          start=start,
                          sr=sr,
                          rootdisk=disksize,
                          use_ipv6=use_ipv6,
                          rawHBAVDIs=rawHBAVDIs)
            # Make sure the tools and kernel are up to date (CA-35375)
            try:
                # Only do this if the tools are out of date, and if we started
                # the VM (CA-35436)
                if start and t.paramGet("PV-drivers-up-to-date") != "true":
                    t.installTools(updateKernel=allowUpdateKernel)
                    # Remove the CD drive to match original behaviour (CA-35385)
                    t.removeCD()
            except Exception, e:
                xenrt.TEC().logverbose("Exception updating tools on Etch VM:"
                                       " %s" % (str(e)))
            
            return t

    def createGenericWindowsGuest(self,
                                  name=None,
                                  drivers=True,
                                  start=True,
                                  sr=None,
                                  distro=None,
                                  arch=None,
                                  vcpus=None,
                                  memory=None,
                                  disksize=None,
                                  use_ipv6=False,
                                  rawHBAVDIs=None):
        """Installs a Windows VM and PV drivers for general test use"""
        
        if not name:
            name = xenrt.randomGuestName(distro="genericwin", arch=arch)
        
        if not distro:
            if arch is not None and arch.endswith("64"):
                distro = self.lookup("GENERIC_WINDOWS_OS_64", "w2k3eesp2-x64")
            else:
                distro = self.lookup("GENERIC_WINDOWS_OS", "w2k3eesp2")
            
        template = self.getTemplate(distro)
        guest = self.guestFactory()(name,
                                    template,
                                    self)

        if vcpus != None:
            guest.setVCPUs(vcpus)
        if memory != None:
            guest.setMemory(memory)
        if arch != None:
            guest.arch = arch
        if disksize == None:
            disksize = guest.DEFAULT
        guest.install(self,
                      distro=distro,
                      isoname=xenrt.DEFAULT,
                      sr=sr,
                      rootdisk=disksize,
                      use_ipv6=use_ipv6,
                      rawHBAVDIs=rawHBAVDIs)
        if xenrt.TEC().tc:
            xenrt.TEC().tc.getLogsFrom(guest)
        if guest.memory > 4096:
            # We added /PAE to boot.ini so we have to reboot before
            # checking the resources
            guest.xmlrpcShutdown()
            guest.poll("DOWN")
            guest.start()
        guest.check()
        if drivers:
            guest.installDrivers()
        if not start:
            guest.shutdown()
        return guest

    def createGenericEmptyGuest(self,
                                vcpus=None,
                                memory=None,
                                name=None):
        if not name:
            name = xenrt.randomGuestName()
        template = xenrt.lib.xenserver.getTemplate(self, "other")
        guest = self.guestFactory()(name, template, self)
        if vcpus != None:
            guest.setVCPUs(vcpus)
        if memory != None:
            guest.setMemory(memory)
        guest.createGuestFromTemplate(template, None)

        return guest
        

    def createBasicGuest(self,
                         distro,
                         vcpus=None,
                         memory=None,
                         name=None,
                         arch="x86-32",
                         sr=None,
                         bridge=None,
                         use_ipv6=False,
                         notools=False,
                         nodrivers=False,
                         disksize=None,
                         rawHBAVDIs=None,
                         primaryMAC=None,
                         reservedIP=None,
                         forceHVM=False
                         ):
        """Installs a VM of the specified distro and installs tools/drivers."""

        (distro, special) = self.resolveDistroName(distro)

        if distro.startswith("generic-"): 
            distro = distro[8:]
        if distro.lower() == "windows" or distro.lower() == "linux":
            distro = self.lookup("GENERIC_" + distro.upper() + "_OS"
                                 + (arch.endswith("64") and "_64" or ""),
                                 distro)

        if not name:
            name = xenrt.randomGuestName(distro=distro, arch=arch)
        
        canUsePrebuiltTemplate = not use_ipv6 and not rawHBAVDIs and not reservedIP and not forceHVM and not primaryMAC
       
        guest = None

        if canUsePrebuiltTemplate:
            guest = xenrt.lib.xenserver.guest.createVMFromPrebuiltTemplate(self,
                                            name,
                                            distro,
                                            vcpus=vcpus,
                                            memory=memory,
                                            vifs=xenrt.lib.xenserver.Guest.DEFAULT,
                                            bridge=bridge,
                                            sr=sr,
                                            arch=arch,
                                            rootdisk=disksize,
                                            notools=notools,
                                            special=special)

        if guest:
            doSetRandomVcpus = not vcpus and self.lookup("RND_VCPUS", default=False, boolean=True)
            doSetRandomCoresPerSocket = self.lookup("RND_CORES_PER_SOCKET", default=False, boolean=True)

            if doSetRandomVcpus or doSetRandomCoresPerSocket:
                guest.shutdown()
                if doSetRandomVcpus:
                    guest.setRandomVcpus()
                if doSetRandomCoresPerSocket:
                    guest.setRandomCoresPerSocket(self, vcpus)
                guest.start()
        else:
            template = xenrt.lib.xenserver.getTemplate(self, distro, forceHVM, arch)
            if re.search(r"etch", template, flags=re.IGNORECASE) or re.search(r"Demo Linux VM", template):
                password = xenrt.TEC().lookup("ROOT_PASSWORD_DEBIAN")
            else:
                password = None
            guest = self.guestFactory()(name, template, password=password)
            guest.primaryMAC=primaryMAC
            guest.reservedIP=reservedIP
            repository = None

            if guest.windows:
                isoname = xenrt.DEFAULT
            else:
                isoname = None
                if not "Etch" in template and not "Sarge" in template and not "Demo Linux VM" in template:
                    repository = xenrt.getLinuxRepo(distro, arch, "HTTP")

            guest.distro = distro
            guest.arch = arch

            if vcpus != None:
                guest.setVCPUs(vcpus)
            elif self.lookup("RND_VCPUS", default=False, boolean=True):
                guest.setRandomVcpus()

            if self.lookup("RND_CORES_PER_SOCKET", default=False, boolean=True):
                guest.setRandomCoresPerSocket(self, vcpus)

            if memory != None:
                guest.setMemory(memory)
            if (not disksize) or disksize == None or disksize == guest.DEFAULT:
                if forceHVM:
                    disksize = 8192 # 8GB (in MB) by default
                else:
                    disksize = guest.DEFAULT
            if primaryMAC:
                if bridge:
                    br = bridge
                else:
                    br = self.getPrimaryBridge()
                vifs = [("%s0" % (guest.vifstem), br, primaryMAC, None)]
            else:
                vifs = guest.DEFAULT
            guest.special.update(special)
            guest.install(self,
                          distro=distro,
                          isoname=isoname,
                          pxe=forceHVM,
                          repository=repository,
                          sr=sr,
                          bridge=bridge,
                          notools=notools,
                          use_ipv6=use_ipv6,
                          rootdisk=disksize,
                          rawHBAVDIs=rawHBAVDIs,
                          vifs=vifs)
            if guest.windows and guest.memory > 4096:
                # We added /PAE to boot.ini so we have to reboot before
                # checking the resources
                guest.xmlrpcShutdown()
                guest.poll("DOWN")
                guest.start()
        if guest.windows and not nodrivers:
            guest.installDrivers()
        if not nodrivers:
            guest.check()
        return guest

    def getDefaultAdditionalCDList(self):
        """Return a list of additional CDs to be installed.
        The list is a string of comma-separated ISO names or None if
        there are no additional CDs. The result is determined
        by the value of CARBON_EXTRA_CDS - if this is not set or set to the
        value of "DEFAULT" then the product default is used. If this is set
        it is used as-is."""
        ecds = self.lookup("CARBON_EXTRA_CDS", None)
        if not ecds or ecds == "DEFAULT":
            ecds = self.lookup("DEFAULT_EXTRA_CDS", "linux.iso")
        if ecds == "NONE":
            ecds = None
        return ecds

    def getSupplementalPackCDs(self):
        """Returns a list of supplemental CDs to be installed."""

        supp_cds = self.lookup("SUPPLEMENTAL_PACK_CDS", None)
        
        if not supp_cds:
            # Look for a release specific Supp Packs, if provided.
            supp_cds = xenrt.TEC().lookup("SUPP_PACK_CDS_%s" %
                                        (self.productVersion.upper()), None)
        
        return supp_cds

    def getVdiMD5Sum(self, vdi):
        """Gets the MD5 sum of the specified VDI"""

        if not (isinstance(vdi, str) or isinstance(vdi, unicode)) or len(vdi) == 0:
            raise xenrt.XRTError("Invalid VDI UUID passed to getVdiMD5Sum()")
        
        # generate random name for script to write in dom0
        tmp = "/tmp/" + xenrt.util.randomGuestName() + "md5.sh"
        
        self.execdom0("echo 'md5sum /dev/${DEVICE}' > " + tmp)
        self.execdom0("chmod u+x " + tmp)
        md5sum = self.execdom0("/opt/xensource/debug/with-vdi %s %s" % (vdi, tmp), timeout=1800).splitlines()[-1].split()[0]
        
        try:
            if "The device is not currently attached" in md5sum:
                raise xenrt.XRTError("Device not attached when trying to md5sum")
        finally:
            self.execdom0("rm -f " + tmp)

        return md5sum

    def getManagementNetworkUUID(self):

        networkUUID = self.parseListForOtherParam("pif-list",
                                              "management",
                                              "true",
                                              "network-uuid",
                                              "host-uuid=%s" % (self.getMyHostUUID()))

        return networkUUID

    def mountImports(self, itype, device, mtype="nfs", fstab=False):
        """Mount an ISO/XGT import directory."""
        self.execdom0("[ -d /var/opt/xen/%s_import ] || "
                      "mkdir -p /var/opt/xen/%s_import" % (itype, itype))
        # Unmount existing if mounted
        mountpoint = "/var/opt/xen/%s_import" % (itype)
        if self.execdom0("mount | grep -q %s" % (mountpoint),
                         retval="code") == 0:
            self.execdom0("umount %s" % (mountpoint))
        # Perform the mount.
        
        # There's been some NFS issues with iptables. XRT-782
        # Use tcpdump to get some data.
        #xenrt.TEC().logverbose("Running tcpdump on Domain-0.")
        #self.execdom0("tcpdump -c 1000 -w /tmp/networkdump -s 30000 &")
        # Wait a second for tcpdump to get going.
        #xenrt.sleep(5)
        
        # Build mount command line.
        c = ["mount", "-oro"]
        if mtype:
            c.append("-t %s" % (mtype))
        c.append(device)
        c.append(mountpoint)
        
        # Try with firewall.
        xenrt.TEC().logverbose("Trying mount without stopping firewall.")
        try:
            self.execdom0(string.join(c))
        except Exception, e:
            if self.execdom0("test -e /etc/init.d/iptables",
                             retval="code") == 0:
                # Oops, maybe we're seeing the NFS problem.
                xenrt.TEC().logverbose("Stopping firewall.")
                self.execdom0("/etc/init.d/iptables stop")
                # Give it a second.
                xenrt.sleep(30)
                xenrt.TEC().logverbose("Trying mount with firewall down.")
                self.execdom0(string.join(c))
                xenrt.TEC().logverbose("Starting firewall.")
                self.execdom0("/etc/init.d/iptables start")
            else:
                raise

        # Add to fstab if required:
        if fstab:
            # Remove any existing references to this mount point
            if self.execdom0("grep -q %s /etc/fstab" % (mountpoint),
                             retval="code") == 0:
                self.execdom0("mv /etc/fstab /etc/fstab.xrtorig && "
                              "grep -v %s /etc/fstab.xrtorig > /etc/fstab"
                              % (mountpoint))
            self.execdom0("echo %s %s %s defaults 0 0 >> /etc/fstab" %
                          (device, mountpoint, mtype))            

    def checkXenCaps(self, cap):
        """Return True if cap is listed in xen_caps"""
        return cap in self.getXenCaps()

    def isHvmEnabled(self):
        """Return True if host is HVM compatible"""
        return "hvm" in self.getHostParam("capabilities")

    def isSvmHardware(self):
        """Return True if host is HVM compatible and has SVM enabled"""
        return self.isHvmEnabled() and re.search(r"AuthenticAMD", self.execdom0("cat /proc/cpuinfo"))

    def isVmxHardware(self):
        """Return True if host is HVM compatible and has VMX enabled"""
        return self.isHvmEnabled() and re.search(r"GenuineIntel", self.execdom0("cat /proc/cpuinfo"))

    def getBridgeWithMapping(self, index):
        """Returns the name of a bridge corresponding to the interface
        specified by the "assumed" enumeration index."""
        if index == 0:
            # Return the bridge associated with the primary NIC
            eth = self.getDefaultInterface()
        else:
            eth = self.getSecondaryNIC(index)
        bridges = self.getBridges()
        index = int(re.search(r"(\d+)$", eth).group(1))
        for stem in ["xenbr", "br", "eth"]:
            bridge = "%s%u" % (stem, index)
            if bridge in bridges:
                return bridge
        raise xenrt.XRTError("Could not find bridge %u on host %s (found %s)" %
                             (index, self.getName(), string.join(bridges)))
    
    def xenstoreRead(self, path):
        return string.strip(self.execdom0("xenstore-read '%s'" % (path)))

    def xenstoreWrite(self, path, value):
        self.execdom0("xenstore-write '%s' '%s'" % (path, value))

    def xenstoreRm(self, path):
        self.execdom0("xenstore-rm '%s'" % (path))

    def xenstoreChmod(self, path, mode):
        self.execdom0("xenstore-chmod '%s' '%s'" % (path, mode))

    def xenstoreList(self, path):
        return string.split(self.execdom0("xenstore-list '%s'" % (path)))

    def xenstoreExists(self, path):
        return self.execdom0("xenstore-exists %s" % path, retval="code") == 0

    def xenstoreWatch(self,
                      path,
                      condition = lambda x: x != None,
                      interval = 5,
                      timeout = None):
        """ Watch a value of a xenstore key. If the condition(value) becomes
        true before timeout, return (True,value) immediately; otherwise return
        (False, value) when timeout. Note that reading a empty key leads to
        None which is itself a valid value, so we can also use this function
        to watch certain key disappearing.
        """
        if timeout == None: deadline = None
        else: deadline = xenrt.util.timenow() + timeout
        while True:
            value = (self.xenstoreExists(path)
                     and self.xenstoreRead(path)
                     or None)
            if condition(value):
                return (True, value)
            else:
                if deadline:
                    waittime = min(interval, deadline - xenrt.util.timenow())
                    if waittime < 0: return(False, value)
                else:
                    waittime = interval
                xenrt.sleep(waittime, log=False)

    def dom0CPUUsage(self):
        usage = self.getXentopData()
        cpuUsage = usage["0"]["CPU(%)"]
        return float(cpuUsage)

    def dom0CPUUsageOverTime(self,secs):
        deadline = xenrt.util.timenow() + secs
        count = 0
        cpuUsageTotal = 0
        while xenrt.util.timenow() < deadline:
            count += 1
            cpuUsageTotal += self.dom0CPUUsage()
        return float(cpuUsageTotal) / float(count)

    def getXentopData(self):
        data = self.execdom0("xentop -f -b -i 2").strip()
        data = [ re.split("[\s]+", x.strip()) for x in data.split("\n") ]
        headings = data[0]
        domains = data[1:]

        reply = {}
        for d in domains:
            entry = dict(zip(headings, d))
            if entry["NAME"].startswith("Domain-"):
                domid = entry["NAME"].strip("Domain-")
            else:
                domid = entry["NAME"]
            reply[domid] = entry

        return reply
    
    def waitForEnabled(self, timeout, level=xenrt.RC_FAIL, desc="Operation"):
        """Wait for a host to become enabled"""
        now = xenrt.util.timenow()
        deadline = now + timeout
        while True:
            try: # CA-78570
                if self.getHostParam("enabled") == "true" and self.getHostParam("host-metrics-live") == "true":
                    return xenrt.RC_OK
            except:
                pass
            if xenrt.util.timenow() > deadline:
                if level == xenrt.RC_FAIL:
                    self.checkHealth()
                return xenrt.XRT("%s timed out" % (desc), level)
            xenrt.sleep(15)

    def waitForXapi(self, timeout, level=xenrt.RC_FAIL, desc="Operation", local=False):
        now = xenrt.util.timenow()
        deadline = now + timeout
        while 1:
            try:
                cli = self.getCLIInstance(local=local)
                
                if local:
                    cli.execute("host-is-in-emergency-mode")
                else:
                    cli.execute("vm-list", "--minimal")
                xenrt.TEC().logverbose("Valid response received from Xapi")
                return xenrt.RC_OK
            except:
                pass

            now = xenrt.util.timenow()
            if now > deadline:
                return xenrt.XRT("%s timed out" % (desc), level)
            xenrt.sleep(15)
            
    def parameterList(self, command, params, argsString=''):
        """Parse the output of an xe list command for 1 or more parameters.
           This returns a list of dictionaries where the keys match the params passed into the function.
             e.g., host.parameterList(command='vm-list', params=['name-label', 'power-state'], argsString='is-control-domain=false')
               could return  [ {'name-label': 'myVM1', 'power-state': 'running'}, { ...}, ...]
        """
        if not isinstance(params, list) or len(params) == 0:
            raise xenrt.XRTError('Invalid call to method: parameterList, 0 or invalid params specified')
        
        c = self.getCLIInstance()
        lines = c.execute(command, 'params=%s %s' % (','.join(params), argsString), strip=True).splitlines()
        # Add an extra blank line at the end to act as a end-of-record marker
        lines.append('')
    
        paramList = []
        entry = None
        for line in lines:
            if line != '':
                if entry == None:
                    # Start new entry
                    entry = {}

                lineData = line.split()
                key = lineData[0].strip()
                if not key in params:
                    raise xenrt.XRTError('Parameter: %s not found in requested list' % (key))
                if entry.has_key(key):
                    raise xenrt.XRTError('Duplicate parameter: %s found in response' % (key))

                # Alt method for getting value:    value = re.sub('.*?%s.*?:' % (key), '', line).strip()
                value = line.split(':', 1)[1].strip()
                # method debug line:    xenrt.TEC().logverbose('Adding KVP.  Key: %s, Value: %s' % (key, value))
                entry[key] = value
            else:
                if entry != None:
                    if len(params) != len(entry.keys()):
                        raise xenrt.XRTError('Not all parameters found in response. Expected: %d, Actual: %d' % (len(params), len(entry.keys())))
                    paramList.append(entry)
                    entry = None

        return paramList
        
        
    def parseListForParam(self, command, uuid, param, args=""):
        """Parse the output of a vm-list etc. command to get the param
        value for the uuid specified"""
        return self.parseListForOtherParam(command, "uuid", uuid, param, args)
        
        
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
        """Parse the output of a vm-list etc, to get one param's value where
        the specified parameter is the specified value"""
        cli = self.getCLIInstance()
        reply = string.split(cli.execute(command,
                                         "%s=\"%s\" %s params=%s" %
                                         (param, str(value).replace('"','\\"'),
                                          args, otherparam),
                                         minimal=True),
                             ",")
        if len(reply) == 0:
            raise xenrt.XRTError("Lookup of %s %s=%s failed" %
                                 (command, param, value))
        if len(reply) > 1:
            xenrt.TEC().warning("Multiple results for lookup of %s %s=%s" %
                                (command, param, value))
        return reply[0]

    def minimalList(self, command, params=None, args=None):
        """Return a list of items returned by a --minimal CLI call"""
        c = self.getCLIInstance()
        a = []
        if params:
            a.append("params=\"%s\"" % (params))
        if args:
            a.append(args)
        clist = c.execute(command, string.join(a), minimal=True)
        if clist == "":
            return []
        #work around of a xapi bug
        if ';' in clist:
            ret = string.split(clist.replace('\\\\','\\'),";")
        else:
            # Work around an xapi bug
            ret = string.split(clist.replace('\\\\','\\'), ",")
        return map(lambda s: s.strip(), ret)
        
    def genParamGet(self, ptype, uuid, param, pkey=None):
        c = self.getCLIInstance()
        args = ["uuid=%s" % (uuid), "param-name=%s" % (param)]
        if pkey:
            args.append("param-key=%s" % (pkey))
        return c.execute("%s-param-get" % (ptype), string.join(args),
                         strip=True)

    def genParamsGet(self, ptype, uuid, param):
        ps = self.genParamGet(ptype, uuid, param)
        return dict(map(lambda x:x.split(": ", 1), ps.split("; ")))

    def genParamSet(self, ptype, uuid, param, value, pkey=None):
        c = self.getCLIInstance()
        args = ["uuid=%s" % (uuid)]
        if pkey:
            args.append("%s-%s=\"%s\"" %
                        (param, pkey, str(value).replace('"', '\\"')))
        else:
            args.append("%s=\"%s\"" % (param, str(value).replace('"', '\\"')))
        return c.execute("%s-param-set" % (ptype), string.join(args),
                         strip=True)

    def genParamClear(self, ptype, uuid, param):
        c = self.getCLIInstance()
        args = ["uuid=%s" % (uuid), "param-name=%s" % (param)]
        c.execute("%s-param-clear" % (ptype), string.join(args))

    def genParamRemove(self, ptype, uuid, param, pkey):
        c = self.getCLIInstance()
        args = ["uuid=%s" % (uuid), "param-name=%s" % (param),
                "param-key=%s" % (pkey)]
        c.execute("%s-param-remove" % (ptype), string.join(args))

    def parseMetadata(self, command, params=None, args=None):
        cli = self.getCLIInstance()
        a = []
        if params: 
            a.append("params='%s'" % (params))
        if args and len(args):
            if type(args) == list:
                a += args
            else:
                a.append(args)
        data = cli.execute(command, " ".join(a))
        results = []
        result = {}
        out = re.findall("(\S+).*\((.*)\)[^:]*: (.*)", data)
        for key,fieldtype,value in out:
            key = key.strip()
            fieldtype = fieldtype.strip()
            value = value.strip()
            if key == "uuid" and result.has_key(key):
                results.append(result)
                result = {}
            if value == "<not in database>" or not value:
                result[key] = None
                continue
            if fieldtype == "RW" or fieldtype == "RO":  
                result[key] = value
            if fieldtype == "SRW" or fieldtype == "SRO":  
                result[key] = map(string.split, value.split(";"))
            if fieldtype == "MRW" or fieldtype == "MRO":
                result[key] = {}
                for item in value.split(";"):
                    k, v = item.rsplit(":", 1) 
                    result[key] = value
        if result.has_key("uuid"):
            results.append(result)
        return results

    def parseConfMulti(self, command, params=None, args=None, index=None):
        cli = self.getCLIInstance()
        arglist = []
        if params: arglist.append("params='%s'" % params)
        if args: arglist.append(args)
        data = cli.execute(command, string.join(arglist))
        linespec = {'sep': ':',
                    'sub': {'post':
                            lambda s: re.search("(\S+).*\((.*)\)",s).groups()},
                    'next': lambda l: (l[0][1].startswith('M')
                                       and {'sep': ';',
                                            'sub': {'sep' : ':',
                                                    'next': lambda _:None},
                                            'post':dict}
                                       or l[0][1].startswith('S')
                                       and {'sep': ';', 'post': set}
                                       or None),
                    'post': lambda l: (l[0][0], l[1])}
        secspec = {'sep': '\n',
                   'sub': linespec,
                   'post': dict}
        spec = {'sep': '\n\n',
                'sub': secspec,
                'post': (index
                         and (lambda l: dict(map(lambda s:(s[index], s), l)))
                         or None)}
        return xenrt.parseLayeredConfig(data, spec)

    def parseConf(self, command, params=None, args=None):
        result = self.parseConfMulti(command, params=params,
                                     args=args, index=None)
        return result[0]

    def getMyHostUUID(self):
        """Get the UUID of this host"""
        if not self.uuid:
            self.uuid = self.getInventoryItem("INSTALLATION_UUID")
        return self.uuid
 
    def getHandle(self):
        """Return an API handle for this host"""
        return self.getAPISession().xenapi.host.get_by_uuid(self.getMyHostUUID()) 

    def getMyDomain0UUID(self):
        """Get the UUID of this host's dom0"""
        if not self.dom0uuid:
            self.dom0uuid = self.getInventoryItem("CONTROL_DOMAIN_UUID")
        return self.dom0uuid
        
    def applyPatch(self, patchfile, returndata=False, applyGuidance=False, patchClean=False):
        """Upload and apply a patch to the host"""
        
        self.addHotfixFistFile(patchfile)

        # back up the original v6d for comparison
        if self.execdom0("test -e /opt/xensource/libexec/v6d", retval="code") == 0:
            self.execdom0("cp -fp /opt/xensource/libexec/v6d /opt/xensource/libexec/v6d.patchorig")
        
        cli = self.getCLIInstance()
        xenrt.TEC().logverbose("Applying patch %s" % (patchfile))
        
        patch_uuid = None
        
        try:
            patch_uuid = cli.execute("patch-upload", "file-name=\"%s\"" % patchfile).strip()
        except xenrt.XRTFailure, e:
            # It's OK if the patch has already been uploaded.
            if not "already exists" in str(e):
                raise
            else:
                m=re.search("uuid: ([\w,-]*)", str(e.data))
                if m:
                    patch_uuid = m.groups()[0]
            
        rpmsBefore = self.execdom0("rpm -qa|sort").splitlines()
        t1 = xenrt.timenow()
        
        data = cli.execute("patch-apply", "uuid=\"%s\" host-uuid=\"%s\"" % (patch_uuid,self.getMyHostUUID()))
        
        t2 = xenrt.timenow()
        xenrt.TEC().comment("Patch apply for %s on %s took %u seconds" % (os.path.basename(patchfile), self.getName(), t2-t1))
        
        rpmsAfter = self.execdom0("rpm -qa|sort").splitlines()
        
        newRpms = filter(lambda x: not x in rpmsBefore, rpmsAfter)
        removedRpms = filter(lambda x: not x in rpmsAfter, rpmsBefore)
        
        xenrt.TEC().logverbose("New RPMS:\n" + "\n".join(newRpms))
        xenrt.TEC().logverbose("Removed RPMS:\n" + "\n".join(removedRpms))
        
        if applyGuidance:
            guidance = self.genParamGet("patch", patch_uuid,"after-apply-guidance")
            self.applyGuidance(guidance)
        
        if patchClean:
            cli.execute("patch-clean", "uuid=\"%s\"" %(patch_uuid))
            
        if returndata:
            return data
    
    def unpackPatch(self, patchfile):
        """Unpack a patch on a XenServer host"""
        workdir = string.strip(self.execdom0("mktemp -d /tmp/XXXXXX"))
        patchname = os.path.basename(patchfile)
        sftp = self.sftpClient()
        try:
            sftp.copyTo(patchfile, os.path.join(workdir, patchname))
        finally:
            sftp.close()

        # First de-sign the hotfix
        with xenrt.GEC().getLock("GPG"):
            self.execdom0("cd %s; gpg --batch --yes -q -d --skip-verify --output %s.raw %s" % (workdir, patchname, patchname))

        # Unpack it
        unpackDir = self.execdom0("cd %s; sh %s.raw unpack" % (workdir, patchname)).strip()
        # Remove the workdir
        self.execdom0("rm -fr %s" % workdir)

        return unpackDir

    def applyGuidance(self, guidance):
        if "restartHost" in guidance:
            xenrt.TEC().logverbose("Rebooting host %s after patch-apply based on after-apply-guidance" % self.getName())
            self.reboot()
            self.waitForXapi(600, desc="Waiting for Xapi Startup after reboot")
        else:
            if "restartXAPI" in guidance:
                xenrt.TEC().logverbose("Restarting toolstack on %s after patch-apply based on after-apply-guidance" % self.getName())
                self.restartToolstack()
            if "restartHVM" in guidance:
                raise xenrt.XRTError("Unimplemented apply guidance 'restartHVM'")
            if "restartPV" in guidance:
                raise xenrt.XRTError("Unimplemented apply guidance 'restartPV'")

    def addHotfixFistFile(self, patchfile):
        if patchfile.endswith(".unsigned") and isinstance(self, xenrt.lib.xenserver.ClearwaterHost):
            sha1 = xenrt.command("sha1sum " + patchfile).strip()
            self.execdom0('echo "%s" > /tmp/fist_allowed_unsigned_patches' % sha1)
    
    def uploadPatch(self, patchfile):
        """Upload a patch to the host"""
        
        self.addHotfixFistFile(patchfile)
        
        cli = self.getCLIInstance()
        return cli.execute("patch-upload",
                           "file-name=\"%s\"" % (patchfile)).strip()

    def destroyPatch(self, uuid):
        """Remove a patch from the host"""
        cli = self.getCLIInstance()
        cli.execute("patch-destroy",
                    "uuid=%s" % (uuid))

    def getUniquePatches(self, patches):
        """Remove duplicate entries in the given patches list
        @param patches: list of patches
        @return: list of unique patches
        """
        uniquePatches = {}
        finalListOfPatches = []
        hotfixParserReg = re.compile('/(?P<hotfixBuild>[A-Z-]*[0-9]+)/(?P<hotfixName>.*)')
        for patch in patches:
            m = hotfixParserReg.search(patch)
            # if patch is "/usr/RTM-77323/XS62ESP1/XS62ESP1.xsupdate"
            #     m.group('hotfixBuild') = 'RTM-77323'
            #     m.group('hotfixName') = 'XS62ESP1/XS62ESP1.xsupdate'
            if m.group('hotfixName') not in uniquePatches:
                finalListOfPatches.append(patch)
                uniquePatches[m.group('hotfixName')] = m.group('hotfixBuild')
            elif uniquePatches[m.group('hotfixName')] != m.group('hotfixBuild'):
                raise xenrt.XRTFailure("Trying to install two builds of same hotfix:%s" % (m.group('hotfixName')))
        return finalListOfPatches

    def uploadBugReport(self):
        xenrt.TEC().logverbose("Uploading bugreport.")
        cli = self.getCLIInstance()
        args = []
        args.append("host=%s" % (self.getMyHostUUID()))
        cli.execute("host-bugreport-upload", string.join(args))

    def checkBugReport(self):
        filename = "/var/ftp/support/%s-bugreport-*.tar.bz2" % (self.getMyHostUUID())
        xenrt.ssh.SSH("support.xensource.com",
                      "ls %s" % (filename),
                      username="%s" % (xenrt.TEC().lookup("SUPPORT_USERNAME")),
                      password="%s" % (xenrt.TEC().lookup("SUPPORT_PASSWORD")))
                      
                      
    def getBridges(self):
        """Return the list of bridges on the host."""
        brs = self.minimalList("network-list", "bridge")
        if len(brs) == 0:
            return None
        return brs

    def removeNetwork(self, bridge=None, nwuuid=None):
        if bridge:
            xenrt.TEC().logverbose("Removing %s" % bridge)
            self.execdom0("ifconfig %s down" % (bridge))
            self.execdom0("brctl delbr %s" % (bridge))
        if not nwuuid:
            nwuuid = self.getNetworkUUID(bridge)
        cli = self.getCLIInstance() 
        cli.execute("network-destroy", "uuid=%s" % (nwuuid))

    def createNetwork(self, name="XenRT bridge"):
        cli = self.getCLIInstance()
        args = []
        args.append("name-label=\"%s\"" % (name))
        args.append("name-description=\"Created by XenRT\"")
        nwuuid = cli.execute("network-create", string.join(args)).strip() 
        try:
            cli.execute("network-attach", "uuid=%s host-uuid=%s" % 
                        (nwuuid, self.getMyHostUUID()))
        except:
            pass
        return nwuuid

    def createVLAN(self, vlan, bridge, nic=None, pifuuid=None):
        """Create a new VLAN on the host and return the untagged PIF UUID."""
        if not pifuuid:
            pifuuid = self.parseListForUUID("pif-list VLAN=-1 host-uuid=%s" %
                                            (self.getMyHostUUID()),
                                            "device",
                                            nic)
        cli = self.getCLIInstance()
        args = []
        args.append("network-uuid=%s" % (bridge))
        args.append("vlan=%u" % (vlan))
        args.append("pif-uuid=%s" % (pifuuid))
        r = cli.execute("vlan-create", string.join(args)).strip()
        try:
            cli.execute("network-attach", "uuid=%s host-uuid=%s" % 
                        (bridge, self.getMyHostUUID()))
        except:
            pass
        return r

    def removeVLAN(self, vlan):
        """Remove a VLAN"""
        # create vlan creates a new untagged pif, but that is 
        # cleaned up when the vlan is destroyed via the vlan uuid
        vlanuuid = self.parseListForUUID("pif-list", "VLAN", vlan,
                                         args="host-uuid=%s" %
                                              (self.getMyHostUUID())) 

        networkuuid = self.genParamGet("pif", vlanuuid, "network-uuid")
        bridge = self.genParamGet("network", networkuuid, "bridge")
        nic = self.genParamGet("pif", vlanuuid, "device")
        vlanif = "%s.%u" % (nic, vlan)
        
        cli = self.getCLIInstance()
        cli.execute("vlan-destroy", "uuid=%s" % (vlanuuid))
        
        try:
            vlanuuid = self.parseListForUUID("pif-list", "VLAN", vlan)
            raise xenrt.XRTFailure("VLAN %d exists." % (vlan))
        except:
            pass
        ifs = self.getBridgeInterfaces(bridge)
        if ifs:
            raise xenrt.XRTFailure("Bridge %s exists on the host." % (bridge))
        try:
            self.execdom0("ifconfig %s" % (vlanif))
            raise xenrt.XRTFailure("Interface %s exists." % (vlanif))
        except:
            pass
        try:
            self.execdom0("ls /proc/net/vlan/%s" % (vlanif))
            raise xenrt.XRTFailure("%s exists in /proc/net/vlan" % (vlanif))
        except:
            pass
    
    def checkVLAN(self, vlan, nic="eth0"):
        """Check VLAN has been installed correctly."""
        vlanuuid = self.parseListForUUID("pif-list", "VLAN", vlan,
                                         args="host-uuid=%s" % 
                                              (self.getMyHostUUID()))
        networkuuid = self.genParamGet("pif", vlanuuid, "network-uuid")
        bridge = self.genParamGet("network", networkuuid, "bridge")
        device = self.genParamGet("pif", vlanuuid, "device")
        vlanif = "%s.%u" % (nic, vlan)

        if device != nic:
            raise xenrt.XRTFailure("NIC mismatch %s != %s." % (device, nic))

        ifs = self.getBridgeInterfaces(bridge)
        if not ifs:
            raise xenrt.XRTFailure("Bridge %s does not exist on the host." % (bridge))
        if not vlanif in ifs:
            raise xenrt.XRTFailure("Bridge %s does not include %s." % (bridge, vlanif))
        try:
            self.execdom0("ifconfig %s" % (vlanif))
        except:
            raise xenrt.XRTFailure("Interface %s does not exist" % (vlanif))
        try:
            self.execdom0("ls /proc/net/vlan/%s" % (vlanif))
        except:
            raise xenrt.XRTFailure("%s does not exist in /proc/net/vlan" % (vlanif))

    def getBonds(self):
        return self.minimalList("bond-list")

    def createBond(self,pifs,dhcp=False,management=False,network=None,mode=None,ignorePifCarrierFor=[]):
        """Create a bond device using the given pifs"""
        if not network:
            network = self.createNetwork()

        cli = self.getCLIInstance()
        args = []
        args.append("network-uuid=%s" % (network))
        args.append("pif-uuids=%s" % (string.join(pifs,",")))
        bondUUID = cli.execute("bond-create",string.join(args)).strip()

        # Find the PIF
        pifUUID = self.parseListForUUID("pif-list", "bond-master-of", bondUUID)

        if dhcp:
            args = []
            args.append("uuid=%s" % (pifUUID))
            args.append("mode=dhcp")
            cli.execute("pif-reconfigure-ip",string.join(args))

        # Add bonding mode, if required (e.g. "active-backup" for active/passive bonding)
        if mode:
            args = []
            args.append("uuid=%s" % (pifUUID))
            args.append("other-config:bond-mode=%s" % mode)
            cli.execute("pif-param-set", string.join(args))

        if management:
            args = []
            args.append("pif-uuid=%s" % (pifUUID))
            try:
                cli.execute("host-management-reconfigure",string.join(args))
            except:
                pass # This triggers an exception as we lose connection etc...
            xenrt.sleep(120)

        # Remove IP from the underlying device
        if dhcp:
            for pif in pifs:
                args = []
                args.append("uuid=%s" % (pif))
                args.append("mode=None")
                cli.execute("pif-reconfigure-ip",string.join(args))

        bridge = self.genParamGet("network", network, "bridge")
        device = self.genParamGet("pif", pifUUID, "device")

        return (bridge, device)

    def removeBond(self, bonduuid, dhcp=False, management=False):
        """Remove the specified bond device and replumb the management
        interface to the first raw PIF"""

        cli = self.getCLIInstance()

        # List the PIFs used by the bond
        pifs = self.genParamGet("bond", bonduuid, "slaves").split("; ")

        # Get the bond device for a later check
        bpif = self.genParamGet("bond", bonduuid, "master")
        bdevice = self.genParamGet("pif", bpif, "device")
        bnetwork = self.genParamGet("pif", bpif, "network-uuid")

        if management:
            # Choose the PIF to be used by the management interface. If we have
            # one that matches the default interface then use that otherwise
            # take the one with the smallest device number
            mpif = None
            devices = {}
            for pif in pifs:
                device = self.genParamGet("pif", pif, "device")
                if device == self.getDefaultInterface():
                    mpif = pif
                    break
                devices[device] = pif
            if not mpif:
                d = devices.keys()
                d.sort()
                mpif = devices[d[0]]

        if dhcp:
            args = []
            args.append("uuid=%s" % (mpif))
            args.append("mode=dhcp")
            cli.execute("pif-reconfigure-ip",string.join(args))

        if management:
            args = []
            args.append("pif-uuid=%s" % (mpif))
            try:
                cli.execute("host-management-reconfigure",string.join(args))
            except:
                pass # This triggers an exception as we lose connection etc...
            xenrt.sleep(120)

        args = []
        args.append("uuid=%s" % (bonduuid))
        cli.execute("bond-destroy", string.join(args))

        # Check the bond has gone away
        try:
            self.getBondInfo(bdevice)
            failed = True
        except xenrt.XRTFailure, e:
            if re.search(r"No bond config", e.reason):
                failed = False
            else:
                failed = True
        if failed:
            raise xenrt.XRTFailure("Bond config still exists for %s" %
                                   (bdevice))

        cli.execute("network-destroy", "uuid=%s" % (bnetwork))

        if management:
            network = self.genParamGet("pif", mpif, "network-uuid")
            bridge = self.genParamGet("network", network, "bridge")
            device = self.genParamGet("pif", mpif, "device")
        else:
            bridge = None
            device = None
        return (bridge, device)

    def getHostParam(self, param, key=None):
        """Get a host parameter"""
        uuid = self.getMyHostUUID()
        cli = self.getCLIInstance()
        args = ["uuid=%s" % (uuid)]
        args.append("param-name=\"%s\"" % (param))
        if key:
            args.append("param-key=\"%s\"" % (key))
        return cli.execute("host-param-get",
                           string.join(args),
                           strip=True)

    def paramGet(self, param, key=None):
        return self.getHostParam(param, key)

    def getSRParam(self, uuid, param):
        """Get a SR param"""
        cli = self.getCLIInstance()
        return cli.execute("sr-param-get",
                           "uuid=%s param-name=%s" % (uuid, param),
                           strip=True)

    def setHostParam(self, param, value):
        uuid = self.getMyHostUUID()
        cli = self.getCLIInstance()
        cli.execute("host-param-set",
                    "uuid=%s %s=\"%s\"" %
                    (uuid, param, str(value).replace('"', '\\"')))

    def paramSet(self, param, value):
        self.setHostParam(param, value)

    def removeHostParam(self, param, key):
        uuid = self.getMyHostUUID()
        cli = self.getCLIInstance()
        cli.execute("host-param-remove",
                    "uuid=%s param-name=%s param-key=%s" % (uuid, param, key))

    def execHelperScript(self, script, args=""):
        self.execdom0("xe-%s %s" % (script, args)) 
        
    def destroyVDI(self, vdiuuid):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (vdiuuid))
        cli.execute("vdi-destroy", string.join(args))

    def createVDI(self, sizebytes, sruuid=None, smconfig=None, name=None):
        if not sruuid:
            sruuid = self.lookupDefaultSR()
        cli = self.getCLIInstance()
        args = []
        if name:
            args.append("name-label=\"%s\"" % (name))
        else:
            if xenrt.TEC().lookup("WORKAROUND_CA174211", False, boolean=True):
                args.append("name-label=\"Created_by_XenRT\"")
            else:
                args.append("name-label=\"Created by XenRT\"")
        args.append("sr-uuid=%s" % (sruuid))
        args.append("virtual-size=%s" % (sizebytes))
        args.append("type=user")
        if smconfig:
            args.append("sm-config:%s" % (smconfig))
        return cli.execute("vdi-create", string.join(args), strip=True)

    def snapshotVDI(self, vdiuuid):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (vdiuuid))
        return cli.execute("vdi-snapshot", string.join(args), strip=True)

    def enableCaching(self, sr=None):
        if not sr:
            cacheDisk = xenrt.TEC().lookup("INTELLICACHE_DISK", None)
            if not cacheDisk:
                sr = self.getLocalSR()
            else:
                srFound=False
                pbds = self.minimalList("pbd-list", "uuid", "host-uuid=%s" % (self.getMyHostUUID()))
                for p in pbds:
                    srs = self.minimalList("sr-list", "uuid", "type=ext PBDs:contains=%s" % p)
                    if len(srs) > 0:
                        device = self.genParamGet("pbd", p, "device-config", "device")
                        if device == "/dev/%s" % cacheDisk:
                            sr = srs[0]
                if not sr:
                    sr = self.getCLIInstance().execute("sr-create", "type=ext device-config:device=/dev/%s host-uuid=%s name-label=cache" % (cacheDisk, self.getMyHostUUID()))
                                                        

        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getMyHostUUID()))
        args.append("sr-uuid=%s" % (sr))
        cli.execute("host-enable-local-storage-caching", string.join(args))

    def disableCaching(self):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getMyHostUUID()))
        cli.execute("host-disable-local-storage-caching", string.join(args))

    def getMyHostName(self):
        """Return a host name-label suitable for e.g. vm-start on="""
        return self.getHostParam("name-label")

    def getMaxMemory(self):
        return int(self.getHostParam("memory-free"))/xenrt.MEGA
    


    def maximumMemoryForVM(self, guest):
        """Return the maximum memory size for a new VM."""
        return self.getFreeMemory()
 
    def getTotalMemory(self):
        return int(self.getHostParam("memory-total"))/xenrt.MEGA

    def getCPUCores(self):
        return len(self.minimalList("host-cpu-list", "number"))

    def getNoOfSockets(self):
        count = "0"
        data = self.paramGet("cpu_info")

        for d in data.split(';'):
            r=re.search(".*socket_count.*\s*\d+",d)
            if r:
                count = re.search("\d+",r.group(0)).group(0)

        if int(count) == 0:
            raise xenrt.XRTFailure("Socket Count returned from CLI: %s" % count)
        else:
            return int(count)

    def getPhysInfo(self):
        data = self.execdom0("/opt/xensource/debug/xenops physinfo")
        return xenrt.util.strlistToDict(data.splitlines())

    def listCrashDumps(self):
        uuid = self.getMyHostUUID()
        return self.minimalList("host-crashdump-list",
                                None,
                                "host-uuid=%s" % (uuid))

    def destroyCrashDump(self,cd):
        cli = self.getCLIInstance()
        cli.execute("host-crashdump-destroy","uuid=%s" % (cd)) 

    def uploadCrashDump(self,cd):
        cli = self.getCLIInstance()
        cli.execute("host-crashdump-upload","uuid=%s" % (cd))

    def cliReboot(self,reboottime=240,sleeptime=240,evacuate=False):
        """Perform a clean reboot of the host"""
        cli = self.getCLIInstance()
        cli.execute("host-disable","uuid=%s" % (self.getMyHostUUID()))
        if evacuate:
            cli.execute("host-evacuate","uuid=%s" % (self.getMyHostUUID()))
        cli.execute("host-reboot","uuid=%s" % (self.getMyHostUUID()))
        xenrt.sleep(reboottime)
        self.waitForSSH(600,desc="Host boot after host-reboot CLI command")
        xenrt.sleep(sleeptime)

    def evacuate(self):
        """Evacuate the host (puts it into maintenance mode)"""
        cli = self.getCLIInstance()
        cli.execute("host-evacuate","uuid=%s" % (self.getMyHostUUID()))

    def enable(self):
        """Enable the host (exits maintenance mode)"""
        cli = self.getCLIInstance()
        cli.execute("host-enable","uuid=%s" % (self.getMyHostUUID()))

    def disable(self):
        """Disables the host"""
        cli = self.getCLIInstance()
        cli.execute("host-disable","uuid=%s" % (self.getMyHostUUID()))
   
    def reboot(self,sleeptime=120,forced=False,timeout=600):
        """Reboot the host and verify it boots"""
        xenrt.GenericHost.reboot(self,forced=forced,timeout=timeout)
        self.postBoot(sleeptime=sleeptime)

    def poweron(self, timeout=600):
        """Power on the host and verify it boots"""
        xenrt.GenericHost.poweron(self, timeout=timeout)
        self.postBoot()

    def postBoot(self, sleeptime=120):
        xenrt.sleep(sleeptime)
        

    def backup(self,filename):
        """Create a backup of this host"""
        cli = self.getCLIInstance()
        cli.execute("host-backup",
                    "file-name=%s host=\"%s\"" %
                    (filename, self.getMyHostName()))

    def restore(self,filename,bringlive=False):
        """Restore a backup of this host, optionally bringing it live"""
        cli = self.getCLIInstance()
        cli.execute("host-restore",
                    "file-name=%s host=\"%s\"" %
                    (filename, self.getMyHostName()))

        if bringlive:
            pass

    def getLicenseDetails(self):
        cli = self.getCLIInstance()
        data = cli.execute("host-license-view", "host-uuid=%s" %
                                                (self.getMyHostUUID()))
        params = ["sku_type", "version", "serialnumber", "expiry", "name",
                  "company", "sku_marketing_name", "grace", "earlyrelease","restrict_hotfix_apply",
                  "restrict_read_caching", "restrict_wlb", "restrict_vgpu"]
        returnData = {}
        for p in params:
            r = re.search(r"%s.*: (.*)" % (p), data)
            if r:
                returnData[p] = r.group(1)

        if not returnData.has_key("sku_type"):
            # Sku type hidden from CLI in this version, use the API instead
            session = self.getAPISession(secure=False)
            try:
                xapi = session.xenapi
                h = xapi.host.get_by_uuid(self.getMyHostUUID())
                try:
                    returnData["sku_type"] = xapi.host.get_license_params(h)['sku_type']
                    xenrt.TEC().logverbose(\
                        "API read of license sku_type = '%s'" %
                        (returnData["sku_type"]))
                except:
                    pass
            finally:
                self.logoutAPISession(session)

        return returnData

    def tailor(self):
        xenrt.GenericHost.tailor(self)
        if self.lookup("DEBUG_CA12048", False, boolean=True):
            xenrt.TEC().warning("Enabling debugging for CA-12048")
            eth = self.getDefaultInterface()
            cmd = "tcpdump -i %s -lne udp port bootps >> /var/log/dhcp.dump 2>&1 &" % (eth)
            self.execdom0("echo '%s' >> /etc/rc.local" % (cmd))
            self.reboot()
        if self.lookup("OPTION_MIAMI_METRICS", False, boolean=True):
            self.setHostParam("other-config:rrd_update_interval", "2")
            self.execdom0("/opt/xensource/bin/xe-toolstack-restart")
        self.storageLinkTailor()
        if self.lookup("DEBUG_CP7440", False, boolean=True):
            # Start a flow count script
            xenrt.TEC().logverbose("Starting flowCheck.sh to monitor the OVS flow table size")
            self.execdom0("%s/flowCheck.sh > /dev/null 2>&1 < /dev/null &" % (xenrt.TEC().lookup("REMOTE_SCRIPTDIR")))

    def storageLinkTailor(self):            
        if self.execdom0("test -e /opt/Citrix/StorageLink/bin", retval="code") == 0:
            # http://support.citrix.com/article/CTX131994
            # Need to update CSLG certs
            try:
                self.execdom0("cd /tmp && wget %s/cvsm.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
                self.execdom0("cd /tmp && tar -xzf cvsm.tgz && /bin/cp -f cvsm/* /opt/Citrix/StorageLink/bin/")
            except:
                # there could be a read-only FS -> OEM editions
                pass
            
    def enableSyslog(self, remoteip):
        """Enable host syslog to a remote server."""
        self.setHostParam("logging-syslog_destination", remoteip)
        cli = self.getCLIInstance()
        cli.execute("host-syslog-reconfigure host-uuid=%s" % (self.getMyHostUUID()))

    def disableSyslog(self):
        """Disable remote syslog, uses local now."""
        try:
            self.removeHostParam("logging", "syslog_destination")
        except xenrt.XRTFailure, e:
            if not re.search(r"Key is not in map", e.data):
                raise e
        cli = self.getCLIInstance()
        cli.execute("host-syslog-reconfigure host-uuid=%s" % (self.getMyHostUUID()))
            
    def getGuestMemory(self, guest, unit = xenrt.MEGA):
        # Sometimes it take a few seconds for xapi to notice a memory
        # change after a migration.
        for i in range(3):
            m = int(self.genParamGet("vm",
                                     guest.getUUID(),
                                     "memory-actual"))/unit
            if m > 0:
                return m
            xenrt.sleep(3)
        return 0
 
    def getGuestVCPUs(self, guest):
        return int(self.genParamGet("vm", guest.getUUID(), "VCPUs-number"))

    def listDomains(self, includeS=False):
        """Return a list of domains and their basic details."""
        reply = {}
        ld = self.execdom0("list_domains -all", idempotent=True)
        for line in string.split(ld, "\n"):
            print line
            fields = string.split(line, "|")
            if len(fields) >= 12:
                if string.strip(fields[0]) == "id":
                    continue
                domname = string.strip(fields[1])
                domid = int(fields[0])
                memory = int(fields[3])
                vcpus = int(fields[9])
                cputime = float(fields[8]) # TODO - what is this measured in?
                state = self.STATE_UNKNOWN
                hvm = False
                notrunning = False
                if string.find(fields[2], "D") > -1:
                    state = self.STATE_DYING
                elif string.find(fields[2], "P") > -1:
                    state = self.STATE_PAUSED
                elif string.find(fields[2], "S") > -1:
                    state = self.STATE_SHUTDOWN
                    if not includeS:
                        notrunning = True
                elif string.find(fields[2], "B") > -1:
                    state = self.STATE_BLOCKED
                elif string.find(fields[2], "R") > -1:
                    state = self.STATE_RUNNING
                if string.find(fields[2], "H") > -1:
                    hvm = True
                if not notrunning:
                    reply[domname] = [domid, memory, vcpus, state, cputime,
                                      hvm]
        return reply


    def importDDK(self,guestname="ddk"):
        """Import the DDK onto this host"""
        g = self.guestFactory()(guestname, "NO_TEMPLATE")
        g.setHost(self)
        g.password = xenrt.TEC().lookup("ROOT_PASSWORD_DDK")

        # Perform the import
        ddkzip = None
        ddkiso = xenrt.TEC().lookup("DDK_CD_IMAGE", None)

        if ddkiso and ddkiso.startswith('/'):
            ddkiso = xenrt.TEC().getFile(ddkiso)
            
        if not ddkiso:
            # Try the same directory as the ISO
            ddkiso = xenrt.TEC().getFile("ddk.iso", "xe-phase-2/ddk.iso")
        if not ddkiso:
            ddkzip = xenrt.TEC().getFile("ddk.zip", "xe-phase-2/ddk.zip")
        if not ddkiso and not ddkzip:
            raise xenrt.XRTError("No DDK ISO/ZIP file given")
        try:
            if ddkiso:
                mount = xenrt.MountISO(ddkiso)
                mountpoint = mount.getMount()
            if ddkzip:
                # XXX Make this a tempDir once we've moved them out of /tmp
                tmp = xenrt.NFSDirectory()
                mountpoint = tmp.path()
                xenrt.command("unzip %s -d %s" % (ddkzip, mountpoint))
            g.importVM(self, "%s/ddk" % (mountpoint))
        finally:
            try:
                if ddkiso:
                    mount.unmount()
                if ddkzip:
                    tmp.remove()
            except:
                pass
        g.memset(g.memory)
        g.cpuset(g.vcpus)
        # Make sure we can boot it
        g.makeNonInteractive()

        return g

    def setXenLogLevel(self):
        """Set Xen Log Level to all"""
        self.execdom0("sed -e 's/\(append .*xen\S*.gz\)/\\0 loglvl=all guest_loglvl=all/' /boot/extlinux.conf > tmp && mv tmp /boot/extlinux.conf -f")
        self.reboot()

    #########################################################################
    # Network operations
    def getPIFUUID(self, device, requirePhysical=False):
        """Return the UUID for a specified PIF device (e.g. eth0)"""
        args = "host-uuid=%s" % (self.getMyHostUUID())
        if requirePhysical:
            args += " physical=true"
        return self.parseListForUUID("pif-list",
                                     "device",
                                     device,
                                     args)

    def getNetworkUUID(self, bridge):
        """
        Return the UUID for a specified PIF device name (e.g. eth0). If a UUID
        is given as argument, just verify it's a network UUID and return it.
        """
        # This is a special case for shared hosts on other networks - we can specify !NPRI, which means NSEC if the shared host is on this network, and NPRI otherwise
        if bridge == "!NPRI":
            nprinet = xenrt.getNetworkParam("NPRI", "SUBNET")
            nprimask = xenrt.getNetworkParam("NPRI", "SUBNETMASK")
            net = IPy.IP("%s/%s" % (nprinet, nprimask))
            if self.getIP() in net:
                bridge = "NSEC"
            else:
                bridge = "NPRI"
        param = xenrt.isUUID(bridge) and "uuid" or "bridge"
        nwuuid = self.parseListForUUID("network-list", param, bridge)
        if not nwuuid:
            nwuuid = self.parseListForUUID("network-list", "other-config:xenrtnetname", bridge)
        if not nwuuid:
            nwuuid = self.parseListForUUID("network-list", "name-label", bridge)
        if not nwuuid and bridge == "NPRI":
            nwuuid = self.getNetworkUUID(self.getPrimaryBridge())
        return nwuuid
    
    def getPrimaryBridge(self):
        """Return the name of the first bridge that is connected to the
        external network. If we have previously tagged a network for
        VM use then use that (or one of them) instead.

        The choice is prioritised if no tagged networks are found:
            1. An NPRI physical interface
            2. A non-NPRI physical interface
            3. A bond or VLAN interface
        """
        try:
            nws = self.minimalList("network-list",
                                   "uuid",
                                   "other-config:xenrtvms=true")
            if len(nws) > 0:
                nw = random.choice(nws)
                return self.genParamGet("network", nw, "bridge")
        except Exception, e:
            xenrt.TEC().warning("Exception whlie looking for VM bridges: %s" %
                                str(e))
        brs = self.getBridges()
        xapibridges = []
        if not brs:
            raise xenrt.XRTError("Could not find any bridges")
        brs.sort()
        secbrs = []
        netmask = self.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"])
        subnet = self.lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET"])
        for br in brs:
            if br[0:4] == "xapi":
                xapibridges.append(br)
                continue
            try:
                data = self.execdom0("ip address show dev %s" % (br))
                r = re.search(r"inet\s+([0-9\.]+)", data)
                if r:
                    # If this is a NPRI address use this bridge
                    if xenrt.isAddressInSubnet(r.group(1), subnet, netmask):
                        return br
                    else:
                        secbrs.append(br)
            except:
                pass
        # Was there a non-NPRI interface?
        if len(secbrs) > 0:
            return secbrs[0]

        # Try any xapi bridges (to pick up bonded interfaces)
        # Sort into reverse order (oldest bridge is likely to be the guest
        # installer one if it's there!)
        xapibridges.sort()
        xapibridges.reverse()
        for br in xapibridges:
            try:
                data = self.execdom0("ip address show dev %s" % (br))
                if re.search(r"inet\s+[0-9\.]+", data):
                    return br
            except:
                pass

        raise xenrt.XRTError("Could not determine which bridge to use")

    def getExternalBridges(self):
        """Return a list of bridge names for bridges that have connections
        to physical network interfaces."""
        # Get list of networks associated with PIFs
        nws = self.minimalList("pif-list",
                               "network-uuid",
                               "host-uuid=%s" % (self.getMyHostUUID()))
        # Look up bridges for those networks
        bridges = []
        for nw in nws:
            bridges.append(self.genParamGet("network", nw, "bridge"))
        return bridges
        
    def changeManagementInterface(self, interface):
        """Change the management interface, set an address and update
        the harness metadata.
        """
        prevuuid = self.parseListForUUID("pif-list",
                                         "management",
                                         "true",
                                         "host-uuid=%s" %
                                         (self.getMyHostUUID())).strip()
        xenrt.TEC().progress("Setting %s mode to DHCP." % (interface))
        nmiuuid = self.parseListForUUID("pif-list",
                                        "device",
                                        interface,
                                        "host-uuid=%s" %
                                        (self.getMyHostUUID())).strip()
        cli = self.getCLIInstance()
        cli.execute("pif-reconfigure-ip uuid=%s mode=dhcp" % (nmiuuid))

        xenrt.TEC().progress("Changing management interface to %s." %
                             (interface))
        try:
            cli.execute("host-management-reconfigure pif-uuid=%s" % (nmiuuid))
        except:
            # This will always return an error.
            pass
        xenrt.sleep(120)

        xenrt.TEC().logverbose("Finding IP address of new management interface...")
        data = self.execdom0("ifconfig xenbr%s" % (interface[-1]))
        nip = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data).group("ip")
        xenrt.TEC().logverbose("Interface %s appears to have IP %s." %
                               (interface, nip))

        xenrt.TEC().logverbose("Start using new IP address.")
        self.machine.ipaddr = nip

        xenrt.TEC().progress("Removing address from previous interface")
        cli.execute("pif-reconfigure-ip uuid=%s mode=None" % (prevuuid))

    def getEthtoolOffloadInfo(self, interface):
        """Get ethtool offload information for the specified interface"""
        data = self.execdom0("ethtool -k %s 2> /dev/null" % (interface))
        info = xenrt.util.strlistToDict(data.splitlines(), sep=":", keyonly=False)
        return dict([(key,info[key]) for key in info if len(info[key]) > 0])

    def getAssumedId(self, friendlyname):
	# Get the network-uuid
	netuuid = self.getNetworkUUID(friendlyname)
	xenrt.TEC().logverbose("getAssumedId: network uuid of network '%s' is %s" % (friendlyname, netuuid))
	if netuuid == '':
            raise xenrt.XRTError("couldn't get network uuid for network '%s'" % (friendlyname))

	# Look up PIF for this network
	args = "host-uuid=%s" % (self.getMyHostUUID())
	pifuuid = self.parseListForUUID("pif-list", "network-uuid", netuuid, args)
	xenrt.TEC().logverbose("getAssumedId: PIF on network %s is %s" % (netuuid, pifuuid))
	if pifuuid == '':
            raise xenrt.XRTError("couldn't get PIF uuid for network with uuid '%s'" % (netuuid))

	# Get the assumed enumeration ID for this PIF
	pifdev = self.genParamGet("pif", pifuuid, "device")
	xenrt.TEC().logverbose("getAssumedId: PIF with uuid %s is %s" % (pifuuid, pifdev))
	if pifdev.startswith("bond"):
            # Get the first bond-slave
            bonduuid = self.genParamGet("pif", pifuuid, "bond-master-of")
            slaveuuids = self.genParamGet("bond", bonduuid, "slaves").split("; ")
            pifuuid = slaveuuids[0]
            pifdev = self.genParamGet("pif", pifuuid, "device")
            xenrt.TEC().logverbose("getAssumedId: bond uuid is %s; using first slave (uuid %s, device %s)" % (bonduuid, pifuuid, pifdev))

	assumedid = self.getNICEnumerationId(pifdev)
	xenrt.TEC().logverbose("getAssumedId: PIF %s corresponds to assumedid %d" % (pifdev, assumedid))
	return assumedid

    def getSecondaryNIC(self, assumedid):
        """ Return the product enumeration name (e.g. "eth2") for the
        assumed enumeration ID (integer)"""
        mac = self.lookup(["NICS", "NIC%u" % (assumedid), "MAC_ADDRESS"], None)
        if not mac:
            raise xenrt.XRTError("NIC%u not configured for %s" %
                                 (assumedid, self.getName()))
        mac = xenrt.util.normaliseMAC(mac)
        # Iterate over pif-list to find a matching device
        pifs = self.minimalList("pif-list",
                                "uuid",
                                "physical=true host-uuid=%s" %
                                (self.getMyHostUUID()))
        for pif in pifs:
            device = self.genParamGet("pif", pif, "device")
            pifmac = self.genParamGet("pif", pif, "MAC")
            if xenrt.util.normaliseMAC(pifmac) == mac:
                return device
        raise xenrt.XRTError("Could not find interface with MAC %s" % (mac))

    def getNICEnumerationId(self, device):
        """Return the assumed enumeration ID (integer) for the given device"""
        
        pif = self.parseListForUUID("pif-list",
                                    "device", 
                                    device,
                                    "physical=true host-uuid=%s" %
                                    (self.getMyHostUUID()))
        mac = self.genParamGet("pif", pif, "MAC")
        if self.lookup("MAC_ADDRESS").upper() == mac.upper():
            return 0
        nicData = self.lookup("NICS")
        for n in nicData.keys():
            if nicData[n]["MAC_ADDRESS"].upper() == mac.upper():
                return int(n.replace("NIC",""))
        raise xenrt.XRTError("Could not find a XenRT NIC for PIF %s (%s)" % (pif, mac)) 

    def getNICPIF(self, assumedid):
        """ Return the PIF UUID for the assumed enumeration ID (integer)"""
        if assumedid == 0:
            mac = self.lookup("MAC_ADDRESS", None)
            if not mac:
                # Fall back to device lookup
                device = self.getDefaultInterface()
                return self.parseListForUUID("pif-list",
                                             "device", 
                                             device,
                                             "physical=true host-uuid=%s" %
                                             (self.getMyHostUUID()))
        else:
            mac = self.lookup(["NICS", "NIC%u" % (assumedid), "MAC_ADDRESS"],
                              None)
        if not mac:
            raise xenrt.XRTError("NIC%u not configured for %s" %
                                 (assumedid, self.getName()))
        mac = xenrt.util.normaliseMAC(mac)
        # Iterate over pif-list to find a matching device
        pifs = self.minimalList("pif-list",
                                "uuid",
                                "physical=true host-uuid=%s" %
                                (self.getMyHostUUID()))
        for pif in pifs:
            pifmac = self.genParamGet("pif", pif, "MAC")
            if xenrt.util.normaliseMAC(pifmac) == mac:
                return pif
        raise xenrt.XRTError("Could not find interface with MAC %s" % (mac))

    def createNetworkTopology(self, topology):
        """Create the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        if not physList: 
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        cli = self.getCLIInstance()

        vlanpifs = []

        # configure single nic non vlan jumbo networks
        requiresReboot = False
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            # create only on single nic non valn nets
            if len(nicList) == 1  and len(vlanList) == 0:
                pif = self.getNICPIF(nicList[0])
                nwuuid = self.genParamGet("pif", pif, "network-uuid")               
                if jumbo == True:
                    cli.execute("network-param-set uuid=%s MTU=9000" % (nwuuid))
                    requiresReboot = True
                elif jumbo != False:
                    cli.execute("network-param-set uuid=%s MTU=%s" % (nwuuid, jumbo))
                    requiresReboot = True

        # Create all bonds
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            if len(nicList) > 1:
                xenrt.TEC().logverbose("Creating bond on %s using %s" %
                                       (network, str(nicList)))
                netname = "%s bond of %s" % (network,
                                             string.join(map(str, nicList)))
                # See if we have a bond network already
                nwuuids = self.minimalList("network-list",
                                     "uuid",
                                     "name-label=\"%s\"" % (netname))
                existing = False
                if len(nwuuids) > 0:
                    xenrt.TEC().logverbose(" ... bond network already exists")
                    nwuuid = nwuuids[0]
                    existing = True
                else:
                    args = []
                    args.append("name-label=\"%s\"" % (netname))
                    args.append("name-description=\"Created by XenRT\"")
                    nwuuid = cli.execute("network-create",
                                         string.join(args)).strip()

                if int(self.execdom0("xe network-list params=all").count("MTU (")) > 0:
                    # Ensure MTU is correct ("jumbo" can be True, False or a number...)
                    currentMTU = self.genParamGet("network", nwuuid, "MTU")
                    if jumbo == True and currentMTU != "9000":
                        self.genParamSet("network", nwuuid, "MTU", "9000")
                        if existing: requiresReboot = True
                    elif jumbo != False and currentMTU != jumbo:
                        self.genParamSet("network", nwuuid, "MTU", str(jumbo))
                        if existing: requiresReboot = True
                    elif currentMTU != "1500":
                        self.genParamSet("network", nwuuid, "MTU", "1500")
                        if existing: requiresReboot = True
                    else:
                        xenrt.TEC().logverbose(" ... current MTU is correct")
    
                # See if we have a bond PIF already
                pifuuid = self.parseListForUUID("pif-list", "network-uuid", nwuuid)
                existing = False
                if pifuuid != '':
                    xenrt.TEC().logverbose(" ... bond PIF already exists")
                    existing = True
                else:
                    pifs = []
                    for nic in nicList:
                        pif = self.getNICPIF(nic)
                        pifs.append(pif)
                    args = []
                    args.append("pif-uuids=%s" % (string.join(pifs, ",")))
                    args.append("network-uuid=%s" % (nwuuid))
                    try:
                        bonduuid = cli.execute("bond-create",
                                           string.join(args)).strip()
                    except:
                        xenrt.sleep(120) # bond-create does host man recofigure
                        bonduuid = self.genParamGet("pif", pifs[0], "bond-slave-of") # CA-61764
                        if not xenrt.isUUID(bonduuid):
                            raise xenrt.XRTError("Couldn't find UUID after creating bond")
                    pifuuid = self.parseListForUUID("pif-list",
                                                    "bond-master-of",
                                                    bonduuid)

                # Add bonding mode, if required (e.g. "active-backup"
                # for active/passive bonding)
                try:
                    currentMode = self.genParamGet("pif", pifuuid, "other-config", "bond-mode")
                except:
                    currentMode = None
                if currentMode != bondMode:
                    if bondMode:
                        self.genParamSet("pif", pifuuid, "other-config", bondMode, pkey="bond-mode")
                    else:
                        self.genParamRemove("pif", pifuuid, "other-config", "bond-mode")
                    # Re-plugging is needed to make the change in bond mode happen
                    if existing: requiresReboot = True
                else:
                    xenrt.TEC().logverbose(" ... current bonding mode is correct")

        # Create all VLANs
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            for v in vlanList:
                vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                xenrt.TEC().logverbose("Creating VLAN %s on %s (%s)" %
                                       (vnetwork, network, str(nicList)))
                netname = "VLAN %s on %s %s" % (vnetwork,
                                                network,
                                                string.join(map(str, nicList)))
                # See if we have one already
                n = self.minimalList("network-list",
                                     "name-label",
                                     "name-label=\"%s\"" % (netname))
                if len(n) > 0:
                    xenrt.TEC().logverbose(" ... already exists")
                else:
                    vid, subnet, netmask = self.getVLAN(vnetwork)
                    if len(nicList) == 1:
                        # raw PIF
                        pif = self.getNICPIF(nicList[0])
                    else:
                        # bond
                        lpif = self.getNICPIF(nicList[0])
                        bond = self.genParamGet("pif", lpif, "bond-slave-of")
                        pif = self.genParamGet("bond", bond, "master")
                    args = []
                    args.append("name-label=\"%s\"" % (netname))
                    args.append("name-description=\"Created by XenRT\"")
                    if jumbo == True:
                        args.append("MTU=9000")
                    elif jumbo != False:
                        args.append("MTU=%d" % jumbo) 
                    nwuuid = cli.execute("network-create",
                                         string.join(args)).strip()
                    args = []
                    args.append("pif-uuid=%s" % (pif))
                    args.append("vlan=%u" % (vid))
                    args.append("network-uuid=%s" % (nwuuid))
                    p = cli.execute("vlan-create", string.join(args)).strip()
                    vlanpifs.append(p)

        self._addIPConfigToNetworkTopology(physList)

        # CA-22381 Plug any VLANs we created
        for pif in vlanpifs:
            try:
                cli.execute("pif-plug", "uuid=%s" % (pif))
            except Exception, e:
                xenrt.TEC().warning("Exception plugging VLAN PIF %s: %s" %
                                    (pif, str(e)))

        # Only reboot if required and once while physlist is processed
        if requiresReboot == True:
            self.reboot()

    def addIPConfigToNetworkTopology(self, topology):
        """Add management and storage IP config to the topology specified
        by XML on this host. Takes either a string containing XML or a XML
        DOM node. This is intended to be used on slaves that have already
        inherited a L2 (bond and VLAN) topology from the the master."""

        physList = self._parseNetworkTopology(topology)
        if not physList:
            xenrt.TEC().logverbose("Empty network configuration.")
            return
        self._addIPConfigToNetworkTopology(physList)

    def _addIPConfigToNetworkTopology(self, physList):
        cli = self.getCLIInstance()

        # First we need to make sure the management interface is moved from
        # a raw PIF to a bond if its raw PIF is now part of a bond. This
        # should not change the IP address of the host.
        mpif = self.parseListForUUID("pif-list",
                                     "management",
                                     "true",
                                     "host-uuid=%s" % (self.getMyHostUUID()))
        b = self.genParamGet("pif", mpif, "bond-slave-of")
        if b and b != "<not in database>":
            xenrt.TEC().logverbose("Moving management to its bond")
            newpif = self.genParamGet("bond", b, "master")
            current = self.genParamGet("pif", mpif, "IP-configuration-mode")
            current = current.lower()
            if current == "dhcp":
                cli.execute("pif-reconfigure-ip",
                            "uuid=%s mode=dhcp" % (newpif))
            elif current == "static":
                ip = self.genParamGet("pif", mpif, "IP")
                netmask = self.genParamGet("pif", mpif, "netmask")
                gateway = self.genParamGet("pif", mpif, "gateway")
                dns = self.genParamGet("pif", mpif, "DNS")
                args = []
                args.append("uuid=%s" % (newpif))
                args.append("mode=static")
                args.append("IP=%s" % (ip))
                args.append("netmask=%s" % (netmask))
                if gateway:
                    args.append("gateway=%s" % (gateway))
                if dns:
                    args.append("DNS=%s" % (dns))
                cli.execute("pif-reconfigure-ip", string.join(args))
            else:
                raise xenrt.XRTError("Unknown existing PIF mode '%s'" %
                                     (current),
                                     "PIF %s" % (mpif))
            try:
                cli.execute("host-management-reconfigure",
                            "pif-uuid=%s" % (newpif))
            except:
                pass
            xenrt.sleep(120)
            cli.execute("pif-reconfigure-ip", "uuid=%s mode=None" % (mpif))

        # Put IP addresses on all interfaces that need them. Note bridges
        # that can take VMs
        managementPIF = None
        IPPIFs = []
        staticPIFs = {}
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            if mgmt or storage:
                xenrt.TEC().logverbose("Putting IP on %s (%s)" %
                                       (network, str(nicList)))
                if len(nicList) == 1:
                    # raw PIF
                    pif = self.getNICPIF(nicList[0])
                else:
                    # bond
                    lpif = self.getNICPIF(nicList[0])
                    bond = self.genParamGet("pif", lpif, "bond-slave-of")
                    pif = self.genParamGet("bond", bond, "master")
                if mgmt and not storage:
                    mode = mgmt
                elif storage and not mgmt:
                    mode = storage
                else:
                    if mgmt == storage:
                        mode = mgmt
                    else:
                        raise xenrt.XRTError(\
                            "Incompatible modes for storage amd mgmt "
                            "functions of this PIF: %s, %s" % (storage, mgmt),
                            "%s (%s)" % (network, str(nicList)))
                current = self.genParamGet("pif", pif, "IP-configuration-mode")
                current = current.lower()
                xenrt.TEC().logverbose("Current mode %s, want %s" %
                                       (current, mode))
                if current == mode:
                    xenrt.TEC().logverbose(" ... already exists")
                elif mode == "dhcp":
                    cli.execute("pif-reconfigure-ip",
                                "uuid=%s mode=dhcp" % (pif))
                elif mode == "static":
                    ip, netmask, gateway = \
                        self.getNICAllocatedIPAddress(nicList[0])
                    args = []
                    args.append("uuid=%s" % (pif))
                    args.append("mode=static")
                    args.append("IP=%s" % (ip))
                    args.append("netmask=%s" % (netmask))
                    staticPIFs[pif] = (ip, netmask)
                    args.append("gateway=%s" % (gateway))
                    if mgmt:
                        dns = self.lookup(["NETWORK_CONFIG",
                                           "DEFAULT",
                                           "NAMESERVERS"], None)
                        if dns:
                            args.append("DNS=%s" % (dns))
                    try:
                        cli.execute("pif-reconfigure-ip", string.join(args))
                    except:
                        pass
                else:
                    raise xenrt.XRTError("Unknown PIF mode '%s'" % (mode),
                                         "%s (%s)" % (network, str(nicList)))
                if storage:
                    self.genParamSet("pif", pif, "disallow-unplug", "true")
                    cli.execute("pif-plug", "uuid=%s" % (pif))
                IPPIFs.append(pif)
                if mgmt and not managementPIF:
                    managementPIF = (pif, "%s (%s)" % (network, str(nicList)))
            
            if len(nicList) == 1:
                # raw PIF
                pif = self.getNICPIF(nicList[0])
                nwuuid = self.genParamGet("pif", pif, "network-uuid")
            else:
                # bond
                netname = "%s bond of %s" % (network,
                                             string.join(map(str, nicList)))
                nwuuid = self.parseListForUUID("network-list",
                                               "name-label",
                                               netname)
            
            if vms:
                xenrt.TEC().logverbose("Putting VMs on %s (%s)" %
                                       (network, str(nicList)))

                self.genParamSet("network",
                                 nwuuid,
                                 "other-config",
                                 "true",
                                 "xenrtvms")

            if friendlynetname:
                with self._getNetNameLock():
                    self.genParamSet("network", nwuuid, "other-config", friendlynetname, "xenrtnetname")

            for v in vlanList:
                vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                if vmgmt or vstorage:
                    xenrt.TEC().logverbose("Putting IP on %s on %s (%s)" %
                                           (vnetwork, network, str(nicList)))
                    vid, subnet, netmask = self.getVLAN(vnetwork)
                    if len(nicList) == 1:
                        # raw PIF
                        tpif = self.getNICPIF(nicList[0])
                    else:
                        # bond
                        lpif = self.getNICPIF(nicList[0])
                        bond = self.genParamGet("pif", lpif, "bond-slave-of")
                        tpif = self.genParamGet("bond", bond, "master")
                    pif = self.parseListForOtherParam("vlan-list",
                                                      "tagged-PIF",
                                                      tpif,
                                                      "untagged-PIF",
                                                      "tag=%u" % (vid))
                    if vmgmt and not vstorage:
                        mode = vmgmt
                    elif vstorage and not vmgmt:
                        mode = vstorage
                    else:
                        if vmgmt == vstorage:
                            mode = vmgmt
                        else:
                            raise xenrt.XRTError(\
                                "Incompatible modes for storage amd mgmt "
                                "functions of this PIF: %s, %s" %
                                (vstorage, vmgmt),
                                "%s (%s)" % (vnetwork, str(nicList)))
                    current = self.genParamGet("pif",
                                               pif,
                                               "IP-configuration-mode")
                    current = current.lower()
                    xenrt.TEC().logverbose("Current mode %s, want %s" %
                                           (current, mode))
                    if current == mode:
                        xenrt.TEC().logverbose(" ... already exists")
                    elif mode == "dhcp":
                        cli.execute("pif-reconfigure-ip",
                                    "uuid=%s mode=dhcp" % (pif))
                    elif mode == "static":
                        raise xenrt.XRTError("Static IP VLAN PIFs not supported",
                                             "%s (%s)" % (vnetwork, str(nicList)))
                    else:
                        raise xenrt.XRTError("Unknown PIF mode '%s'" % (mode),
                                             "%s (%s)" % (vnetwork, str(nicList)))
                    if vstorage:
                        self.genParamSet("pif", pif, "disallow-unplug", "true")
                        cli.execute("pif-plug", "uuid=%s" % (pif))
                    IPPIFs.append(pif)
                    if vmgmt and not managementPIF:
                        managementPIF = (pif, "%s on %s (%s)" %
                                         (vnetwork, network, str(nicList)))
                
                netname = "VLAN %s on %s %s" % (vnetwork,
                                                network,
                                                string.join(map(str, nicList)))
                xenrt.TEC().logverbose("Putting VMs on %s (%s)" %
                                       (network, str(nicList)))
                nwuuid = self.parseListForUUID("network-list",
                                               "name-label",
                                               netname)
                
                if vvms:
                    self.genParamSet("network",
                                     nwuuid,
                                     "other-config",
                                     "true",
                                     "xenrtvms")

                if vfriendlynetname:
                    with self._getNetNameLock():
                        self.genParamSet("network", nwuuid, "other-config", vfriendlynetname, "xenrtnetname")

        # Switch management to the required interface
        if managementPIF:
            pif, desc = managementPIF
            xenrt.TEC().logverbose("Putting management on %s" % (desc))
            # XRT-3934 Check if it's already there
            if self.genParamGet("pif", pif, "management") == "true":
                xenrt.TEC().logverbose(" ... already there")
            else:
                previp = self.getIP()
                try:
                    cli.execute("host-management-reconfigure",
                                "pif-uuid=%s" % (pif))
                except:
                    pass
                xenrt.sleep(120)
                newip = self.execdom0("xe host-param-get uuid=%s "
                                      "param-name=address" %
                                      (self.getMyHostUUID())).strip()
                self.machine.ipaddr = newip

        # Remove IP addresses from any interfaces that shouldn't have them
        allpifs = self.minimalList("pif-list",
                                   "uuid",
                                   "host-uuid=%s" % (self.getMyHostUUID()))
        for pif in allpifs:
            if pif in IPPIFs:
                if pif != managementPIF[0] and pif in staticPIFs.keys():
                    ip, netmask = staticPIFs[pif]
                    args = []
                    args.append("uuid=%s" % (pif))
                    args.append("mode=static")
                    args.append("IP=%s" % (ip))
                    args.append("netmask=%s" % (netmask))
                    cli.execute("pif-reconfigure-ip", string.join(args))
                continue
            ip = self.genParamGet("pif", pif, "IP-configuration-mode")
            if ip != "None":
                xenrt.TEC().logverbose("Removing IP from %s" % (pif))
                cli.execute("pif-reconfigure-ip", "uuid=%s mode=None" % (pif))

        # Make sure we can still run CLI commands
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over new "
                                   "management interface.")

    def presetManagementInterfaceForTopology(self, topology):
        """Move the management interface to where it is eventually intended
        to be. If it is intended to be on a bond then move to the first NIC
        that will form that bond. This is to be used to make sure slaves have
        management interfaces on the correct subnet before we trying to
        join them to a pool. This does not work for management interfaces
        on VLANs."""
        physList = self._parseNetworkTopology(topology)
        currentMPIF = self.parseListForUUID("pif-list",
                                            "management",
                                            "true",
                                            "host-uuid=%s" %
                                            (self.getMyHostUUID()))
        cli = self.getCLIInstance()
        
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p

            if mgmt or storage:
                xenrt.TEC().logverbose("Putting management IP on %s (%s)" %
                                       (network, str(nicList)))
                # Either a raw PIF or the first in the bond
                pif = self.getNICPIF(nicList[0])
                if pif == currentMPIF:
                    xenrt.TEC().logverbose(" ... already configured")
                else:
                    # TODO: generalise for non-DHCP
                    current = self.genParamGet("pif",
                                               pif,
                                               "IP-configuration-mode")
                    if current != "None":
                        xenrt.TEC().logverbose(" ... IP already exists")
                    else:
                        cli.execute("pif-reconfigure-ip",
                                    "uuid=%s mode=dhcp" % (pif))
                    previp = self.getIP()
                    try:
                        cli.execute("host-management-reconfigure",
                                    "pif-uuid=%s" % (pif))
                    except:
                        pass
                    xenrt.sleep(120)
                    newip = self.execdom0("xe host-param-get uuid=%s "
                                          "param-name=address" %
                                          (self.getMyHostUUID())).strip()
                    self.machine.ipaddr = newip
                    cli.execute("pif-reconfigure-ip",
                                "uuid=%s mode=None" % (currentMPIF))

        # Check VLANs
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            for v in vlanList:
                vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                if vmgmt:
                    raise xenrt.XRTError(\
                        "presetManagementInterfaceForTopology not supported "
                        "for VLAN management interfaces")

    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        cli = self.getCLIInstance()

        managementPIF = None
        IPPIFs = []

        # Check bonds
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            if len(nicList) > 1:
                xenrt.TEC().logverbose("Checking bond on %s using %s" %
                                       (network, str(nicList)))
                netname = "%s bond of %s" % (network,
                                             string.join(map(str, nicList)))
                # Ensure we only have one network for this bond
                n = self.minimalList("network-list",
                                     "uuid",
                                     "name-label=\"%s\"" % (netname))
                if len(n) == 0:
                    raise xenrt.XRTFailure("Could not find network for '%s'"
                                           % (netname))
                if len(n) > 1:
                    raise xenrt.XRTFailure("Found multiple networks for '%s'"
                                           % (netname))
                # Get the PIF for this network on this host
                pifstring = self.genParamGet("network", n[0], "PIF-uuids")
                if pifstring == "":
                    raise xenrt.XRTFailure("Network '%s' has no PIFs" %
                                           (netname))
                npifs = pifstring.split("; ")
                hpifs = self.minimalList("pif-list",
                                         "uuid",
                                         "host-uuid=%s" %
                                         (self.getMyHostUUID()))
                pif = None
                for p in npifs:
                    if p in hpifs:
                        pif = p
                        break
                if not pif:
                    raise xenrt.XRTFailure("Could not find PIF for '%s' on "
                                           "this host" % (netname),
                                           "host %s" % (self.getName()))
                # Get the bond for this PIF
                bond = self.genParamGet("pif", pif, "bond-master-of")
                if not xenrt.isUUID(bond):
                    raise xenrt.XRTFailure("'%s' bond PIF does not "
                                           "reference bond" % (netname),
                                           "PIF %s -> %s" % (pif, bond))
                mpif = self.genParamGet("bond", bond, "master")
                if mpif != pif:
                    raise xenrt.XRTFailure("Inconsistency in bond master "
                                           "references for '%s'" % (netname),
                                           "PIF %s, master %s" % (pif, mpif))
                # Get the PIFs for the slaves
                pifstring = self.genParamGet("bond", bond, "slaves")
                if pifstring == "":
                    raise xenrt.XRTFailure("Bond for '%s' has no slave PIFs" %
                                           (netname),
                                           "Master PIF %s bond %s" %
                                           (pif, bond))
                spifs = pifstring.split("; ")
                cpifs = map(lambda x:self.getNICPIF(x), nicList)
                for cpif in cpifs:
                    if not cpif in spifs:
                        raise xenrt.XRTFailure("A PIF is missing from the "
                                               "bond for '%s'" % (netname),
                                               "PIF %s" % (cpif))
                for spif in spifs:
                    if not spif in cpifs:
                        raise xenrt.XRTFailure("An extra PIF is in the "
                                               "bond for '%s'" % (netname),
                                               "PIF %s" % (spif))
                for spif in spifs:
                    b = self.genParamGet("pif", spif, "bond-slave-of")
                    if b != bond:
                        raise xenrt.XRTFailure("Inconsistency in bond slave "
                                               "references for '%s'" % (netname),
                                               "PIF %s" % (spif))
                # Make sure the bond PIF has the same MAC as the first NIC
                # in the bond
                bmac = self.genParamGet("pif", pif, "MAC")
                bmac = xenrt.normaliseMAC(bmac)
                nmac = self.getNICMACAddress(nicList[0])
                nmac = xenrt.normaliseMAC(nmac)
                if bmac != nmac:
                    raise xenrt.XRTFailure("Bond '%s' MAC is not the same as "
                                           "the first NIC" % (netname),
                                           "bond %s, NIC %s" % (bmac, nmac))
                # Check the bond mode is set correctly
                try:
                    currentMode = self.genParamGet("pif", pif, "other-config", "bond-mode")
                except:
                    currentMode = None
                if currentMode != bondMode:
                    raise xenrt.XRTFailure("Bond mode is not set correctly in xapi.",
                                           "Found %s, but should be %s" % (currentMode, bondMode))
                # Check the bond is correctly set up in dom0 (need to be plugged)
                if plugtest or \
                        (mgmt and not ignoremanagement) or \
                        (storage and not ignorestorage):
                    if not ((mgmt and not ignoremanagement) or \
                            (storage and not ignorestorage)):
                        # Won't necessarily be plugged
                        cli.execute("pif-plug", "uuid=%s" % (pif))
                    device = self.genParamGet("pif", pif, "device")
                    (info, slaves) = self.getBondInfo(device)
                    if len(slaves) != len(spifs):
                        raise xenrt.XRTFailure("Incorrect number of interfaces "
                                               "in '%s' bond" % (netname),
                                               "Found %u, should be %u" %
                                               (len(slaves), len(spifs)))
                    for spif in spifs:
                        sdevice = self.genParamGet("pif", spif, "device")
                        if not slaves.has_key(sdevice):
                            raise xenrt.XRTFailure("Device %s missing from '%s' "
                                                   "bond" % (sdevice, netname))
                    if bondMode and (info["mode"] == None or not bondMode in info["mode"]):
                        raise xenrt.XRTFailure("Bond mode is not set correctly on bond device.",
                                               "Found %s, but should be %s" % (info["mode"], bondMode))
            else:
                # Not bonded
                netname = "%s (%u)" % (network, nicList[0])
                pif = self.getNICPIF(nicList[0])
                b = self.genParamGet("pif", pif, "bond-master-of")
                if b and xenrt.isUUID(b):
                    raise xenrt.XRTFailure("Non-bonded NIC claims to be a "
                                           "bond master %s" % (netname))
                b = self.genParamGet("pif", pif, "bond-slave-of")
                if b and xenrt.isUUID(b):
                    raise xenrt.XRTFailure("Non-bonded NIC claims to be a "
                                           "bond slave %s" % (netname))

            # Check management and storage IP configuration
            if mgmt:
                if not managementPIF:
                    managementPIF = pif
                mexp = "true"
            else:
                mexp = "false"
            if mgmt or storage:
                IPPIFs.append(pif)
            i = self.genParamGet("pif", pif, "IP-configuration-mode")
            ip = self.genParamGet("pif", pif, "IP")
            if not ignoremanagement:
                m = self.genParamGet("pif", pif, "management")
                if m != mexp:
                    if mexp == "true":
                        msg = "Management not enabled"
                    else:
                        msg = "Management enabled"
                    raise xenrt.XRTFailure("%s on '%s'" % (msg, netname))
                if mgmt and i == "None":
                    raise xenrt.XRTFailure("Management '%s' missing IP "
                                           "configuration" % (netname))
                if mgmt and not ip:
                    # Try again after a brief pause
                    xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                           "checking again...")
                    xenrt.sleep(30)
                    ip = self.genParamGet("pif", pif, "IP")
                    if not ip:
                        raise xenrt.XRTFailure("Management '%s' missing IP "
                                               "address" % (netname))
            if not ignorestorage:
                if storage and i == "None":
                    raise xenrt.XRTFailure("Storage '%s' missing IP "
                                           "configuration" % (netname))
                if storage and not ip:
                    # Try again after a brief pause
                    xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                           "checking again...")
                    xenrt.sleep(30)
                    ip = self.genParamGet("pif", pif, "IP")
                    if not ip:
                        raise xenrt.XRTFailure("Storage '%s' missing IP "
                                               "address" % (netname))
            if not ignoremanagement and not ignorestorage:
                if (not mgmt and not storage) and i != "None":
                    raise xenrt.XRTFailure("'%s' has IP configuration "
                                           "but is not management or "
                                           "storage" % (netname))
            # TODO: check the IP addresses in dom0 are on the right
            # devices
                
        # Check VLANs
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            for v in vlanList:
                vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                vid, subnet, netmask = self.getVLAN(vnetwork)
                xenrt.TEC().logverbose("Checking VLAN %s on %s (%s)" %
                                       (vnetwork, network, str(nicList)))
                netname = "VLAN %s on %s %s" % (vnetwork,
                                                network,
                                                string.join(map(str, nicList)))
                # Ensure we only have one network for this bond
                n = self.minimalList("network-list",
                                     "uuid",
                                     "name-label=\"%s\"" % (netname))
                if len(n) == 0:
                    raise xenrt.XRTFailure("Could not find network for '%s'"
                                           % (netname))
                if len(n) > 1:
                    raise xenrt.XRTFailure("Found multiple networks for '%s'"
                                           % (netname))
                # Get the PIF for this network on this host
                pifstring = self.genParamGet("network", n[0], "PIF-uuids")
                if pifstring == "":
                    raise xenrt.XRTFailure("Network '%s' has no PIFs" %
                                           (netname))
                npifs = pifstring.split("; ")
                hpifs = self.minimalList("pif-list",
                                         "uuid",
                                         "host-uuid=%s" %
                                         (self.getMyHostUUID()))
                pif = None
                for p in npifs:
                    if p in hpifs:
                        pif = p
                        break
                if not pif:
                    raise xenrt.XRTFailure("Could not find PIF for '%s' on "
                                           "this host" % (netname),
                                           "host %s" % (self.getName()))
                # Check the PIF has the correct VLAN tag
                v = self.genParamGet("pif", pif, "VLAN")
                if v != str(vid):
                    raise xenrt.XRTFailure("VLAN PIF for %s did not have "
                                           "correct VLAN ID" % (netname),
                                           "PIF %s VLAN %u but was '%s'" %
                                           (pif, vid, v))
                # Get the tagged PIF we expect this to connect to
                if len(nicList) == 1:
                    # raw PIF
                    exppif = self.getNICPIF(nicList[0])
                else:
                    # bond
                    lpif = self.getNICPIF(nicList[0])
                    bond = self.genParamGet("pif", lpif, "bond-slave-of")
                    exppif = self.genParamGet("bond", bond, "master")
                # Make sure the VLAN plumbing is correct
                vlanuuid = self.parseListForUUID("vlan-list",
                                                 "tagged-PIF",
                                                 exppif,
                                                 "tag=%u" % (vid))
                if not vlanuuid:
                    raise xenrt.XRTFailure("Could not find VLAN object for "
                                           "'%s'" % (netname))
                upif = self.genParamGet("vlan", vlanuuid, "untagged-PIF")
                if upif != pif:
                    raise xenrt.XRTFailure("VLAN PIF inconsistency for '%s'" %
                                           (netname),
                                           "%s vs %s" % (upif, pif))
                # Check the config in dom0 (need to be plugged)
                if plugtest or \
                        (vmgmt and not ignoremanagement) or \
                        (vstorage and not ignorestorage):
                    if not ((vmgmt and not ignoremanagement) or \
                            (vstorage and not ignorestorage)):
                        # Won't necessarily be plugged
                        cli.execute("pif-plug", "uuid=%s" % (pif))
                    tdevice = self.genParamGet("pif", pif, "device")
                    self.checkVLAN(vid, tdevice)

                # Check management and storage IP configuration
                if vmgmt:
                    if not managementPIF:
                        managementPIF = pif
                    mexp = "true"
                else:
                    mexp = "false"
                if vmgmt or vstorage:
                    IPPIFs.append(pif)
                i = self.genParamGet("pif", pif, "IP-configuration-mode")
                ip = self.genParamGet("pif", pif, "IP")
                if not ignoremanagement:
                    m = self.genParamGet("pif", pif, "management")
                    if m != mexp:
                        if mexp == "true":
                            msg = "Management not enabled"
                        else:
                            msg = "Management enabled"
                        raise xenrt.XRTFailure("%s on '%s'" % (msg, netname))
                    if vmgmt and i == "None":
                        raise xenrt.XRTFailure("Management '%s' missing IP "
                                               "configuration" % (netname))
                    if vmgmt and not ip:
                        # Try again after a brief pause
                        xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                               "checking again...")
                        xenrt.sleep(30)
                        ip = self.genParamGet("pif", pif, "IP")
                        if not ip:
                            raise xenrt.XRTFailure("Management '%s' missing "
                                                   "IP address" % (netname))
                if not ignorestorage:
                    if vstorage and i == "None":
                        raise xenrt.XRTFailure("Storage '%s' missing IP "
                                               "configuration" % (netname))
                    if vstorage and not ip:
                        # Try again after a brief pause
                        xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                               "checking again...")
                        xenrt.sleep(30)
                        ip = self.genParamGet("pif", pif, "IP")
                        if not ip:
                            raise xenrt.XRTFailure("Storage '%s' missing IP "
                                                   "address" % (netname))
                if not ignoremanagement and not ignorestorage:
                    if (not vmgmt and not vstorage) and i != "None":
                        raise xenrt.XRTFailure("'%s' has IP configuration "
                                               "but is not management or "
                                               "storage" % (netname))
                # TODO: check the IP addresses in dom0 are on the right
                # devices
    def getOvsVersion(self):
        """Return openvSwitch version on the host""" 
        return self.execdom0("ovs-vsctl --version | grep 'ovs-vsctl' | sed -n -e 's/^.*(Open vSwitch) //p'").strip()
    
    #########################################################################
    # Storage operations
    def getSRs(self, type=None, local=False):
        """List our SR UUIDs"""
        # Get a list of SRs mounted on this host for filtering
        mySRs = self.minimalList("pbd-list",
                                 "sr-uuid",
                                 "host=%s" % (self.getMyHostUUID()))
        cli = self.getCLIInstance()
        if type:
            data = cli.execute("sr-list", "type=%s --minimal" % (type),
                               compat=False)
        else:
            data = cli.execute("sr-list", "--minimal", compat=False,
                               strip=True)
        data = string.strip(data)
        if data == "":
            return []
        reply = []
        for f in string.split(data, ","):
            if f in mySRs and f != TEMPLATE_SR_UUID:
                reply.append(f)
        return reply

    def getSRByName(self, name):
        """Returns a list containing SR UUIDs"""

        sruuid = self.minimalList("sr-list",
                                 "uuid",
                                 "name-label=%s" % (name))

        if len(sruuid) < 1:
            raise xenrt.XRTError("Could not find suitable SR of given kind")
        else:
            return sruuid

    def getLocalSR(self):
        """Return a local SR UUID"""
        srl = self.getSRs(type="ext", local=True)
        if len(srl) == 0:
            srl = self.getSRs("lvm", local=True)
        if len(srl) == 0:
            srl = self.getSRs("btrfs", local=True)
        if len(srl) == 0:
            raise xenrt.XRTError("Could not find suitable local SR")
        return srl[0]
   
    def hasLocalSR(self):
        """Returns True if the host has a local SR"""
        if len(self.getSRs(type="ext", local=True)) > 0:
            return True
        if len(self.getSRs(type="lvm", local=True)) > 0:
            return True
        return False

    def removeLocalSR(self):
        """Removes a local SR on the host"""
        for vdiuuid in self.minimalList("vdi-list",
                                        "uuid",
                                        "sr-uuid=%s" % (self.getLocalSR())):
            self.destroyVDI(vdiuuid)
        self.destroySR(self.getLocalSR())
 
    

    def getIQN(self):
        return self.getHostParam("other-config", "iscsi_iqn")

    def getVDISR(self, vdiuuid):
        return self.genParamGet("vdi", vdiuuid, "sr-uuid")

    def getVBDSR(self, vbduuid):
        vdiuuid = self.genParamGet("vbd", vbduuid, "vdi-uuid")
        return self.getVDISR(vdiuuid)

    def createFileSR(self,srsize=None,createVDI=True):
        """Create an empty SR of size srsize MB"""
        # Generate a random file name
        name = ""
        for i in random.sample("ABCDEFGHIJKLMNOPQRSTUVWXYZ",8):
            name += i
        cli = self.getCLIInstance()        
        if createVDI:
            # Create an LVM volume of the right size
        
            vdiuuid = self.createVDI(srsize * xenrt.MEGA)
        
            device = self.genParamGet("vm", self.getMyDomain0UUID(), "allowed-VBD-devices").split(";")[0]
        
            vbduuid = cli.execute("vbd-create", "vm-uuid=%s vdi-uuid=%s device=%s" %
                   (self.getMyDomain0UUID(), vdiuuid, device)).strip()
        
            cli.execute("vbd-plug", "uuid=%s" % vbduuid)
        
            dom0device = self.genParamGet("vbd", vbduuid, "device")
        
            self.execdom0("mkfs.ext3 /dev/%s" % (dom0device))

            # Create a mountpoint for it
            self.execdom0("mkdir -p %s/SRs/%s" % 
                       (xenrt.TEC().lookup("LOCAL_BASE"),name))
            # Mount it
            self.execdom0("mount /dev/%s %s/SRs/%s" % 
                       (dom0device,xenrt.TEC().lookup("LOCAL_BASE"),name))

        # Create the SR
        args = []
        args.append("name-label=XenRT_%s" % (name))
        args.append("physical-size=1")
        args.append("type=file")
        args.append("content-type=\"XenRT Content\"")
        args.append("host-uuid=%s" % (self.getMyHostUUID()))
        if createVDI:
            args.append("device-config-location=%s/SRs/%s/sr" % 
                       (xenrt.TEC().lookup("LOCAL_BASE"),name))
        else: #just use a temporary directory
            args.append("device-config-location=%s/%s" % 
                       (xenrt.TEC().lookup("LOCAL_BASE"),name))
                       
        return cli.execute("sr-create", string.join(args), strip=True)
        
    def destroyFileSR(self,uuid,destroyVDI=True):
        cli = self.getCLIInstance()

        # Find the device
        pbds = self.minimalList("pbd-list",args="sr-uuid=%s" % (uuid))
        location = self.genParamGet("pbd", pbds[0], "device-config", "location")
        

        # Unplug the PBD
        for pbd in pbds:
            cli.execute("pbd-unplug","uuid=%s" % (pbd))

        # Remove the SR
        cli.execute("sr-forget","uuid=%s" % (uuid))

        if destroyVDI:
            # Umount the SR
            location = location[:-3]
            device = self.execdom0("mount | grep '%s' | awk '{print $1}'" % location).strip()[5:]
            self.execdom0("umount %s" % location)
            
            #Unplug the vbd and destroy the vdi
            vbd = self.minimalList("vbd-list", args="device=%s" % device)[0]
            cli.execute("vbd-unplug", "uuid=%s" % vbd)
            vdi = self.genParamGet("vbd", vbd, "vdi-uuid")
            cli.execute("vdi-destroy", "uuid=%s" % vdi)
        else: #just remove the temp directory
            self.execdom0("rm -rf %s" % location)

    def destroySR(self,uuid):

        # Populate all PBDs, slave first.
        if self.pool:
            cli = self.pool.master.getCLIInstance()
            pbds = []
            # getHosts() put master at the last.
            for slave in self.pool.getHosts():
                pbds.extend(self.pool.master.minimalList("pbd-list",args="sr-uuid=%s host-uuid=%s" % (uuid, slave.uuid)))
        else:
            cli = self.getCLIInstance()
            pbds = self.minimalList("pbd-list",args="sr-uuid=%s" % (uuid))

        # Unplug the PBDs
        for pbd in pbds:
            cli.execute("pbd-unplug","uuid=%s" % (pbd))

        # Remove the SR
        cli.execute("sr-destroy","uuid=%s" % (uuid))

    def forgetSR(self,uuid):
        cli = self.getCLIInstance()

        # Unplug the PBDs
        pbds = self.minimalList("pbd-list",args="sr-uuid=%s" % (uuid))
        for pbd in pbds:
            cli.execute("pbd-unplug","uuid=%s" % (pbd))

        # Remove the SR
        cli.execute("sr-forget","uuid=%s" % (uuid))

    def makeLocalNFSSR(self):
        """Uses space on a local LVM SR to provide a locally hosted NFS
        SR."""
        sr = self.getLocalSR()
        vgdata = string.split(\
            self.execRawStorageCommand(sr, "vgs --noheadings -o name,vg_free_count "
                          "--separator=,"), ",")
        vg = string.strip(vgdata[0])
        vgsize = string.strip(vgdata[1])
        self.execRawStorageCommand("lvcreate -n nfsserver -l %s %s" % (vgsize, vg), sr)
        dev = "/dev/%s/nfsserver" % (vg)
        self.execdom0("mkfs.ext3 %s" % (dev))
        self.execdom0("mkdir -p /nfsserver")
        self.execdom0("echo '%s /nfsserver ext3 defaults 0 0' >> /etc/fstab" %
                      (dev))
        self.execdom0("echo '/nfsserver *(sync,rw,no_root_squash)' >> "
                      "/etc/exports")
        self.execdom0("/sbin/chkconfig nfs on")
        self.execdom0("/sbin/chkconfig iptables off")
        self.execdom0("mv /etc/sysconfig/network /etc/sysconfig/network.orig")
        self.execdom0("sed -e's/^PMAP_ARGS/#PMAP_ARGS/' "
                      "< /etc/sysconfig/network.orig > /etc/sysconfig/network")
        self.execdom0("echo '%s' >> /etc/rc.local" % self.modifyRawStorageCommand(sr, "lvchange -ay %s" % vg))
        self.execdom0("echo 'mount /nfsserver' >> /etc/rc.local")
        self.reboot()
        nfssr = xenrt.lib.xenserver.NFSStorageRepository(self, "localnfssr")
        nfssr.create(self.getIP(), "/nfsserver")
        self.addSR(nfssr, default=True)

    def lookupDefaultSR(self):
        """Returns the UUID of the default SR for the pool/host."""
        if self.pool:
            sruuid = self.pool.getPoolParam("default-SR")
        else:
            pooluuid = self.minimalList("pool-list")[0]
            sruuid = self.genParamGet("pool", pooluuid, "default-SR")
        if not re.search(r"not in database", sruuid):
            return sruuid
        raise xenrt.XRTError("Could not find default-SR on !" + self.getName())

    def checkSRs(self, type=["lvm"]):
        """Check if given SRs are working fine, create and delete vdi"""
        sruuid = []
        for srtype in type:
            sruuid.extend(self.getSRs(type=srtype, local=True))
        cli = self.getCLIInstance()
        for sr  in sruuid:
            # Create a 256M VDI on the SR
                args = []
                args.append("name-label='XenRT Test VDI on %s'" % (sr))
                args.append("sr-uuid=%s" % (sr))
                args.append("virtual-size=268435456") # 256M
                args.append("type=user")
                vdi = cli.execute("vdi-create", string.join(args), strip=True)
                
                # Now delete it
                cli.execute("vdi-destroy","uuid=%s" % (vdi))

    def getDBCompatVersion(self):
        try:
            data = self.execdom0("cat /opt/xensource/etc/initial-inventory | "
                                 "grep XAPI_DB_COMPAT_VERSION").strip()           
            # This comes out as e.g. '5.0', so we need to strip off the quotes...
            dcv = data.split("=")[1].strip()[1:-1]
            return "/%s" % (dcv)
        except:
            # For compatibility with Miami
            return ""

    def setupSharedDB(self, lun, existing=False):
        """Create a new remote database on an iSCSI LUN."""
        # Warn if we have VMs running
        if len(self.listGuests()) > 0:
            xenrt.TEC().warning("Trying to set up a remote database on a "
                                "host with VMs running.")
        # Warn if we are a pool slave
        if self.pool and self.pool.master != self:
            xenrt.TEC().warning("Trying to set up a remote database on a"
                                "slave")
        self.sharedDBlun = lun
        chap = lun.getCHAP()
        if chap:
            u, s = chap
        else:
            u = "\"\""
            s = "\"\""

        sharedDB = "%s %s %s %s %u" % (lun.getServer(),
                                       u,
                                       s,
                                       lun.getTargetName(),
                                       lun.getLunID())

        if existing:
            cmd = "xenrt-setup2"
        else:
            cmd = "xenrt-setup"
        try:
            self.execdom0("/etc/init.d/xapi stop")
            self.execdom0("python /opt/xensource/sm/shared_db_util.py %s %s" %
                          (cmd, sharedDB))
            lun.sharedDB = self # This is so it can be cleaned up later
            self.execdom0("/etc/init.d/xapi start")

        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Exception while setting up shared "
                                   "database: " + str(e),data=e.data)
        self.checkSharedDB()

    def checkSharedDB(self):

        dbconf = self.execdom0("cat /etc/xensource/db.conf")
        dcv = self.getDBCompatVersion()
        
        if not self.sharedDBlun:
            # Shared DB is not supposed to be configured, verify this
            devices = string.split(self.execdom0("mount | "
                                                 "grep /var/xapi/shared_db | "
                                                 "awk '{print $1}'"))
            if len(devices) != 0:
                raise xenrt.XRTFailure("/var/xapi/shared_db is mounted when "
                                       "we have no remote database set up")
            
            # Make sure no database has ended up locally where the mount
            # would have been
            if self.execdom0("test -e /var/xapi/shared_db%s/db/state.db" % (dcv),
                             retval="code") == 0:
                raise xenrt.XRTFailure("/var/xapi/shared_db%s/db/state.db "
                                       "exists when we have no remote "
                                       "database set up" % (dcv))

            # Verify that the db.conf does not refer to a remote database
            if re.search(r"is_on_remote_storage:true", dbconf):
                raise xenrt.XRTFailure("Remote storage found in db.conf")

            # Verify that db.conf does not refer to
            # /var/xapi/shared_db/db/state.db
            if re.search(r"/var/xapi/shared_db%s/db/state.db" % (dcv), dbconf):
                raise xenrt.XRTFailure("Reference to "
                                       "/var/xapi/shared_db%s/db/state.db found "
                                       "in db.conf" % (dcv))
            
            return
    
        # Verify that the db.conf refers to a remote database
        if not re.search(r"is_on_remote_storage:true", dbconf):
            raise xenrt.XRTFailure("No remote storage found in db.conf")

        # Verify that db.conf refers to /var/xapi/shared_db/db/state.db
        if not re.search(r"/var/xapi/shared_db%s/db/state.db" % (dcv), dbconf):
            raise xenrt.XRTFailure("No reference to "
                                   "/var/xapi/shared_db%s/db/state.db found "
                                   "in db.conf" % (dcv))
        
        # Verify the filesystem has been mounted
        devices = string.split(self.execdom0("mount | "
                                             "grep /var/xapi/shared_db | "
                                             "awk '{print $1}'"))
        if len(devices) == 0:
            raise xenrt.XRTFailure("/var/xapi/shared_db not mounted after "
                                   "remote database setup")
        if len(devices) > 1:
            raise xenrt.XRTFailure("Mount multiple mounts for "
                                   "/var/xapi/shared_db: %s" %
                                   (string.join(devices)))

        # Verify the xapi database exists
        if self.execdom0("test -e /var/xapi/shared_db%s/db/state.db" % (dcv),
                         retval="code") != 0:
            raise xenrt.XRTFailure("/var/xapi/shared_db%s/db/state.db does not "
                                   "exist after remote database setup" % (dcv))

        # Verify the remote database is at least as up to date as the flash one
        remotegen = int(self.execdom0(\
            "cat /var/xapi/shared_db%s/db/state.db.generation" % (dcv)))
        localgen = int(self.execdom0("cat /var/xapi/state.db.generation"))
        if remotegen < localgen:
            raise xenrt.XRTFailure("Remote database generation %u is older "
                                   "than the local %u" % (remotegen, localgen))

    def disableSharedDB(self):
        """Disable the remote iSCSI database and return the LUN object."""
        if not self.sharedDBlun:
            return None
        self.execdom0("/etc/init.d/xapi stop")
        self.execdom0("umount /var/xapi/shared_db")
        self.execdom0("rm -f /etc/xensource/remote.db.conf")
        self.execdom0("/bin/cp -f /etc/xensource/local.db.conf"
                      " /etc/xensource/db.conf")
        self.execdom0("/etc/init.d/xapi start")
        lun = self.sharedDBlun
        lun.sharedDB = None
        self.sharedDBlun = None
        self.checkSharedDB()
        return lun

    def waitForCoalesce(self, sruuid, timeoutsecs=1200):
        if self.execdom0("test -e /opt/xensource/sm/cleanup.py",
                         retval="code") != 0:
            return
        if self.lookup("DOES_NOT_COALESCE", False, boolean=True):
            return
        # Wait for coalesce activity to complete by running sr-scan and
        # polling for the GC/coalesce to be not running using cleanup.py -q
        # Repeat to ensure the coalesce started after this method was called
        cli = self.getCLIInstance()
        for i in range(2):
            cli.execute("sr-scan", "uuid=%s" % (sruuid))
            xenrt.sleep(5)
            deadline = xenrt.timenow() + timeoutsecs
            ok = False
            while xenrt.timenow() < deadline:
                data = self.execdom0(\
                    "/opt/xensource/sm/cleanup.py -u %s -q" % (sruuid))
                if re.search(r"Currently running: False", data):
                    ok = True
                    break
                xenrt.sleep(10)
            if not ok:
                raise xenrt.XRTFailure(\
                    "Timed out waiting for coalesce to complete", sruuid)

    def toolsISOPath(self):
        """Return the dom0 path to the tools ISO."""
        vdi = self.parseListForUUID("vdi-list",
                                    "name-label",
                                    "xs-tools.iso")
        
        isobasename = self.genParamGet("vdi", vdi, "location")
        sruuid = self.genParamGet("vdi", vdi, "sr-uuid")
        pbd = self.parseListForUUID("pbd-list",
                                    "sr-uuid",
                                    sruuid,
                                    "host-uuid=%s" %
                                    (self.getMyHostUUID()))
            
        isopath = self.genParamGet("pbd", pbd, "device-config", "location")
        return "%s/%s" % (isopath, isobasename)

    #########################################################################
    # P2V support
    def p2v(self, guestname, distro, sourcehost, cd=None):

        guest = self.guestFactory()(\
            guestname,
            "NO_TEMPLATE_NEEDED_FOR_P2V_GUEST",
            password=xenrt.TEC().lookup("ROOT_PASSWORD"))
        guest.setHost(self)
        guest.distro = distro
        self.addGuest(guest)

        sourcehost.password = xenrt.TEC().lookup("ROOT_PASSWORD")
        sourcehost.preCloneTailor()
        
        # Check and lookup variables and files
        if cd == None:
            cdf = xenrt.TEC().lookup("P2V_CD_IMAGE", None)
            if cdf:
                cd = xenrt.TEC().getFile(cdf)
                if not cd:
                    raise xenrt.XRTError("Failed to find P2V CD image")
            else:
                imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
                xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
                cd = xenrt.TEC().getFile("xe-phase-1/%s" % (imageName), imageName)
                if not cd:
                    raise xenrt.XRTError("No CD image supplied.")
        
        xenrt.checkFileExists(cd)

        serport = sourcehost.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = sourcehost.lookup("SERIAL_CONSOLE_BAUD", "115200")
                                     
        comport = str(int(serport) + 1)
        xen_extra_args = sourcehost.lookup("XEN_EXTRA_ARGS", None)
        xen_extra_args_user = sourcehost.lookup("XEN_EXTRA_ARGS_USER", None)
        if xen_extra_args_user:
            xen_extra_args_user = string.replace(xen_extra_args_user, ",", " ")
        dom0_extra_args = sourcehost.lookup("DOM0_EXTRA_ARGS", None)
        dom0_extra_args_user = sourcehost.lookup("DOM0_EXTRA_ARGS_USER", None)
        workdir = xenrt.TEC().getWorkdir()
        
        # Get a PXE directory to put boot files in
        pxe = xenrt.PXEBoot()

        # Pull installer boot files from CD image and put into PXE
        # directory
        xenrt.TEC().logverbose("Using ISO %s" % (cd))
        mount = xenrt.MountISO(cd)
        mountpoint = mount.getMount()
        pxe.copyIn("%s/boot/*" % (mountpoint))
        pxe.copyIn("%s/install.img" % (mountpoint))

        # Create a web directory for the answerfile
        packdir = xenrt.WebDirectory()
        
        # Create the P2V answerfile
        password = self.password
        if not password:
            password = self.lookup("ROOT_PASSWORD")
        ansfile = "%s/%s.xml" % (workdir, sourcehost.getName())
        ans = file(ansfile, "w")
        anstext = """<?xml version="1.0"?>
<conversion>
  <root>sda2</root>
  <target>
    <host>%s</host>
    <user>root</user>
    <password>%s</password>
    <sr>%s</sr>
    <size>8192</size>
    <vm-name>%s</vm-name>
  </target>
</conversion>
""" % (self.getIP(), password, guest.chooseSR(), guestname)
        ans.write(anstext)
        ans.close()
        packdir.copyIn(ansfile)
        xenrt.TEC().copyToLogDir(ansfile)
    
        # Set the boot files and options for PXE
        pxe.setSerial(serport, serbaud)
        pxe.addEntry("local", boot="local")
        pxecfg = pxe.addEntry("p2v", default=1, boot="mboot")
        xenfiles = glob.glob("%s/boot/xen*" % (mountpoint))
        xenfiles.extend(glob.glob("%s/boot/xen.gz" % (mountpoint)))
        if xenrt.TEC().lookup("OPTION_LEGACY_XEN", False, boolean=True):
            xenfiles.extend(glob.glob("%s/boot/legacy.gz" % (mountpoint)))
        if len(xenfiles) == 0:
            raise xenrt.XRTError("Could not find a xen* file to boot")
        xenfile = os.path.basename(xenfiles[-1])
        kernelfiles = glob.glob("%s/boot/vmlinuz*" % (mountpoint))
        if len(kernelfiles) == 0:
            raise xenrt.XRTError("Could not find a vmlinuz* file to boot")
        kernelfile = os.path.basename(kernelfiles[-1])
        pxecfg.mbootSetKernel(xenfile)
        pxecfg.mbootSetModule1(kernelfile)
        pxecfg.mbootSetModule2("install.img")
        
        pxecfg.mbootArgsKernelAdd("watchdog")
        pxecfg.mbootArgsKernelAdd("com%s=%s,8n1" % (comport, serbaud))
        pxecfg.mbootArgsKernelAdd("console=com%s,tty" % (comport))
        pxecfg.mbootArgsKernelAdd("dom0_mem=752M")
        if xen_extra_args:
            pxecfg.mbootArgsKernelAdd(xen_extra_args)
            xenrt.TEC().warning("Using installer extra Xen boot args %s" %
                                (xen_extra_args))
        if xen_extra_args_user:
            pxecfg.mbootArgsKernelAdd(xen_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Xen boot args %s" %
                                (xen_extra_args_user))
        
        pxecfg.mbootArgsModule1Add("root=/dev/ram0")
        pxecfg.mbootArgsModule1Add("console=tty0")
        pxecfg.mbootArgsModule1Add("console=ttyS%s,%sn8" % (serport, serbaud))
        pxecfg.mbootArgsModule1Add("ramdisk_size=65536")
        pxecfg.mbootArgsModule1Add("p2v")
        pxecfg.mbootArgsModule1Add("rt_answerfile=%s" %
                                   (packdir.getURL("%s.xml" %
                                                   (sourcehost.getName()))))
        pxecfg.mbootArgsModule1Add("output=ttyS0")
        if dom0_extra_args:
            pxecfg.mbootArgsModule1Add(dom0_extra_args)
            xenrt.TEC().warning("Using installer extra Dom0 boot args %s" %
                                (dom0_extra_args))
        if dom0_extra_args_user:
            pxecfg.mbootArgsModule1Add(dom0_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Dom0 boot args %s"
                                % (dom0_extra_args_user))
        
        # Set up PXE for installer boot
        pxefile = pxe.writeOut(sourcehost.machine)
        xenrt.TEC().copyToLogDir(pxefile)

        # We're done with the ISO now
        mount.unmount()

        # Reboot the source host into the installer
        if False:
            sourcehost.machine.powerctl.cycle()
        else:
            sourcehost.execcmd("/sbin/reboot")
        xenrt.TEC().progress("Rebooted source host to start P2V.")

        # HACK - wait five minutes and change PXE back to local to stop
        # us booting back into P2V and looping on VM creates
        xenrt.sleep(300)
        pxe.setDefault("local")
        pxe.writeOut(sourcehost.machine)

        # Wait a bit longer and check we actually have a guest
        xenrt.sleep(240)
        if not guest.getUUID() or guest.getUUID() == "":
            raise xenrt.XRTFailure("P2V VM didn't get created")

        # We now poll for the guest going down and having no VIFs
        try:
            guest.poll("DOWN", timeout=4800)
        except xenrt.XRTFailure, e:
            if re.search("Timed out waiting for VM", e.reason):
                # See if it looks like CA-28712
                domid = guest.getDomid()
                data = guest.getHost().guestConsoleLogTail(domid, lines=3)
                if re.search("Fatal error: exception "
                             "Stunnel.Stunnel_error\(\"Connection refused\"\)",
                             data):
                    raise xenrt.XRTFailure("P2V failed, VM reports stunnel "
                                           "connection refused")
                if re.search("Fatal error: exception "
                             "Stunnel.Stunnel_error\(\"\"\)",
                             data):
                    if re.search("netfront: Bad rx response", data):
                        raise xenrt.XRTFailure(\
                            "P2V failed, VM reports stunnel "
                            "error and netfront: Bad rx response")
                    raise xenrt.XRTFailure("P2V failed, VM reports stunnel "
                                           "error")
                if re.search("No DHCPOFFERS received", data):
                    raise xenrt.XRTFailure("P2V server VM did not get DHCP "
                                           "address")

            # Now check the p2v source host serial log if available
            serlog = string.join(\
                sourcehost.machine.getConsoleLogHistory()[-30:], "\n")
            if "P2V FAILED" in serlog:
                r = re.search("(P2VServerError: .+)$",
                              serlog,
                              re.MULTILINE)
                if r:
                    desc = r.group(1).replace("^M", "")
                else:
                    desc = "P2V FAILED"
                raise xenrt.XRTFailure("P2V client reports: %s" % (desc))
            raise e
        deadline = xenrt.timenow() + 180
        while True:
            vifs = guest.getHost().minimalList("vif-list",
                                               args="vm-uuid=%s" %
                                               (guest.getUUID()))
            if len(vifs) == 0:
                break
            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Timed out waiting for P2Ved guest "
                                       "temporary VIF to disappear")
            xenrt.sleep(15)

        # Add a VIF
        br = self.getPrimaryBridge()
        if not br:
            raise xenrt.XRTError("Host has no bridge")
        guest.vifs = [("%s0" % (guest.vifstem), br, xenrt.randomMAC(), None)]
        for v in guest.vifs:
            eth, bridge, mac, ip = v
            guest.createVIF(eth, bridge, mac)

        guest.start()

        return guest
        
    def uninstallAllGuests(self):
        """Uninstall all guests on this host."""
        cli = self.getCLIInstance()

        # If there are no VMs other than the control domain just return
        if len(self.minimalList("vm-list",
                                args="is-control-domain=false")) == 0:
            return

        # Shutdown any running guests (this will error if any are already
        # shutdown so wrap in try, except)
        try:
            cli.execute('vm-shutdown','param-name=\"other-config\" param-key=\"perfmon\"')
        except:
            pass

        # Do the uninstall
        cli.execute("vm-uninstall","force=true --multiple")
                      

    def removeTemplate(self, templateuuid):
        """Remove a template."""
        cli = self.getCLIInstance()
        # There is no template-uninstall so turn the template into a VM
        # before using vm-uninstall on it.
        cli.execute("template-param-set",
                    "uuid=%s is-a-template=false" % (templateuuid))
        cli.execute("vm-uninstall", "uuid=%s --force" % (templateuuid))

    def getAPISession(self, username=None, password=None, local=False,
                      slave=False, secure=True):
        """Return a logged in Xen API session to this host/pool."""
        if not username:
            username = "root"
        if not password:
            if self.password: 
                password = self.password
            else: 
                password = xenrt.TEC().lookup("ROOT_PASSWORD")
        if not secure and xenrt.TEC().lookup("FORCE_API_SECURE", False, boolean=True):
            secure = True
        if self.pool and not local:
            return self.pool.getAPISession(username=username,
                                           password=password,
                                           slave=slave, secure=secure)
        else:
            useIP = self.getIP()
            if ':' in useIP:
                useIP = '[%s]'%useIP
            xenrt.TEC().logverbose("Creating %s API session to %s with (%s, %s). " \
                                   "Local is %s and slave is %s." % \
                                   (secure and "secured" or "non-secured",
                                    useIP, username.encode('ascii', 'replace'),
                                    password.encode('ascii', 'replace'), local, slave))
            if secure:
                v = sys.version_info
                if v.major == 2 and ((v.minor == 7 and v.micro >= 9) or v.minor > 7):
                    xenrt.TEC().logverbose("Disabling certificate verification on >=Python 2.7.9")
                    ssl._create_default_https_context = ssl._create_unverified_context
                session = XenAPI.Session('https://%s:443' % useIP)
            else:
                session = XenAPI.Session('http://%s' % useIP)
            if slave:
                ptoken = self.execdom0("cat /etc/xensource/ptoken").strip()
                session.slave_local_login(ptoken)
            else:
                session.login_with_password(username, password)
            return session

    def logoutAPISession(self, session):
        """Logout from a Xen API session."""
        session.xenapi.session.logout()
    
    def restartToolstack(self):
        self.execdom0("/opt/xensource/bin/xe-toolstack-restart")

    def startXapi(self):
        self.execdom0("service xapi start")

    def verifyHostFunctional(self, migrateVMs=False):
        """Verify that the host and it's guests are all functional"""
        
        # 1. Check the host is accessible over ssh, and that xapi is functioning
        self.execdom0("xe pool-list")

        # 2. Check the host is accessible with the off-host CLI
        cli = self.getCLIInstance()
        cli.execute("pool-list")

        failedGuests = []
        # 3. Check the VMs are functional
        for g in self.guests.keys():
            try:
                self.guests[g].verifyGuestFunctional(migrate=migrateVMs)
            except Exception, e:
                xenrt.TEC().reason("Failed to verify guest %s - %s" % (g, str(e)))
                failedGuests.append(g)
        if len(failedGuests) > 0:
            raise xenrt.XRTFailure("Failed to verify guests %s" % ", ".join(failedGuests))

    def listGuests(self, running=False):
        """Return a list of names of guests on this host."""
        if running:
            vms = self.minimalList("vm-list",
                                   "name-label",
                                   "power-state=running resident-on=%s" % (self.getMyHostUUID()))
        else:
            vms = self.minimalList("vm-list", "name-label")
        reply = []
        for i in vms:
            if not string.find(i, "Control domain on host:") > -1:
                reply.append(i)
        return reply
        
    def checkVersionSpecific(self):
        if self.execdom0("test -e /var/xapi/firstboot-SR-commands",
                         retval="code") == 0:
            xenrt.TEC().reason("/var/xapi/firstboot-SR-commands still exists")
            raise xenrt.XRTFailure("/var/xapi/firstboot-SR-commands still "
                                   "exists")
        started = xenrt.timenow()
        deadline = started + 600
        ok = False
        while xenrt.timenow() < deadline:
            if self.execdom0("test -e /var/xapi/firstboot-SR-commands.started",
                             retval="code") != 0:
                ok = True
                break
            xenrt.sleep(30)
        if not ok:
            xenrt.TEC().reason("/var/xapi/firstboot-SR-commands.started still "
                               "exists")
            raise xenrt.XRTFailure("/var/xapi/firstboot-SR-commands.started "
                                   "still exists")
                                   
    def getGuestUUID(self, guest):
        """Return the UUID of the specified guest."""
        return self.parseListForUUID("vm-list", "name-label", guest.name)
    
    def license(self, sku="XE Enterprise", expirein=None, v6server=None, applyedition=True, edition=None):
        """Apply a license to the host"""
    
        keyfile = None

        if expirein:
            password = xenrt.TEC().lookup("LICENSE_PASSWORD", None)
            if not password:
                raise xenrt.XRTError("Cannot generate license with specific "
                                     "expiry without LICENSE_PASSWORD")

            # Build up POST vars
            # (sockets is informational only at present)
            keyvars = ["output=file", "name=xenrt", "company=XenSource", 
                       "address1=", "address2=", "city=", "state=", 
                       "postalcode=", "country=", "serial=", "sockets=128"]
            if expirein:
                expiretime = time.time() + (3600*24*expirein)
                keyvars.append("expiry=%s" % (time.strftime("%Y-%m-%d",
                                              time.localtime(expiretime))))
            else:
                keyvars.append("expiry=2020-12-31")

            if sku == "XE Enterprise" or sku == "FG Paid":
                keyvars.append("sku_type=1")
            elif sku == "XE Server":
                keyvars.append("sku_type=2")
            elif sku == "XE Express" or sku == "FG Free":
                keyvars.append("sku_type=3")
            else:
                raise xenrt.XRTError("Asked to license unknown sku!")

            # Get version (productRevision minus the build number)
            if not self.productRevision:
                self.checkVersion()
            ver = self.productRevision.split("-")[0]
            keyvars.append("version=%s" % (ver))        
    
            # Generate the file
            keyfile = xenrt.TEC().tempFile()
            username = xenrt.TEC().lookup("LICENSE_USERNAME", "xensource")
            password = xenrt.TEC().lookup("LICENSE_PASSWORD")
            extras = ""
            xenrt.command("wget %s -O %s --post-data '%s' "
                          "https://%s:%s@licensing.xensource.com/cgi-bin/"
                          "license_server.cgi" % (extras,
                                                  keyfile,
                                                  string.join(keyvars,"&"),
                                                  username,password),nolog=True)

        else:
            # Use a static one
            sku = self.lookup(["LICMAP", sku.replace(" ", "_")], sku)
            keyfile = ("%s/keys/xenserver/%s/%s" % 
                      (xenrt.TEC().lookup("XENRT_CONF"),
                       self.productVersion,sku.replace(" ","_")))

        xenrt.TEC().copyToLogDir(keyfile)

        # Apply the license file to the host
        cli = self.getCLIInstance()
        cli.execute("host-license-add", "license-file=%s host-uuid=%s" % 
                                        (keyfile,self.getMyHostUUID()))

        # Sleep 60 seconds to allow xapi to restart etc
        xenrt.sleep(60)

        # Define a table of SKU translations
        skuNames = {"FG Free": ["XE Express", "free"],
                    "FG Paid": ["XE Server", "XE Enterprise", "enterprise", "platinum"]}

        # Check the license has been applied
        details = self.getLicenseDetails()
        if not details.has_key("sku_type"):
            raise xenrt.XRTError("Unable to find current license SKU")
        if details["sku_type"] != sku:
            if not sku in skuNames or not details["sku_type"] in skuNames[sku]:
                raise xenrt.XRTFailure("Licensed SKU '%s' is not what we "
                                       "asked for ('%s')" % (details["sku_type"], sku))

    def setIQN(self, iqn):
        """Set our iSCSI initiator IQN"""
        self.execHelperScript("set-iscsi-iqn", iqn)
        #try:
        #    self.removeHostParam("other-config", "iscsi_iqn")
        #except:
        #    pass
        #self.setHostParam("other-config-iscsi_iqn", iqn)
        
    def submitToHCL(self):
        self.uploadBugReport()
        
    def lifecycleOperationMultiple(self,
                                   guestlist,
                                   command,
                                   force=False,
                                   no_on=False,
                                   timeout=7200,
                                   timer=None):
        """Perform a basic VM lifecycle operation on multiple guests"""
        # Tag the guests
        unique = "xenrt_%u" % (random.randint(0, 999999))
        try:
            for guest in guestlist:
                guest.paramSet("other-config-%s" % (unique), "true")
            cli = self.getCLIInstance()
            flags = ["other-config-%s=true" % (unique)]
            if force:
                flags.append("--force")
            flags.append("--multiple")
            if command in ('vm-start', 'vm-resume') and self.pool and not no_on:
                # With pooling we can make these happen on a specified host
                flags.append("on=\"%s\"" % (self.getMyHostName()))
            if timer:
                timer.startMeasurement()
            cli.execute(command, string.join(flags), timeout=timeout)
            if timer:
                timer.stopMeasurement()
        finally:
            try:
                for guest in guestlist:
                    guest.paramRemove("other-config", unique)
            except:
                pass
                
    def updateTemplates(self):
        """Refresh our list of template names."""
        self.templates = self.minimalList("template-list", "name-label")
        
    def findISOs(self):
        # Return a list of all ISOs on the host
        # Note: May return non ISOs if the name ends with .iso

        # Not using cd-list as this will include CD drives
        vdis = self.minimalList("vdi-list", "name-label")
        isos = []
        for vdi in vdis:
            if vdi.endswith(".iso"):
                isos.append(vdi)

        return isos
        
    def createISOSR(self, device):
        self.execHelperScript("mount-iso-sr", device)

    def addSR(self, sr, default=False):
        """Add an SR object to the list of SRs this host knows about."""
        self.srs[sr.name] = sr
        if default:
            self.defaultsr = sr.name
            
    def getTemplate(self, distro, hvm=None, arch=None):
        template = None
        try:
            if distro == "w2k3eesp2pae":
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_2003_PAE")
            elif re.search("w2k3", distro):
                if re.search("x64", distro):
                    try:
                        template = self.chooseTemplate(\
                            "TEMPLATE_NAME_WINDOWS_2003_64")
                        if not template:
                            template = self.chooseTemplate(\
                                "TEMPLATE_NAME_WINDOWS_2003")
                    except:
                        template = self.chooseTemplate(\
                            "TEMPLATE_NAME_WINDOWS_2003")
                else:
                    template = self.chooseTemplate(\
                        "TEMPLATE_NAME_WINDOWS_2003")
            elif re.search("w2k", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_2000")
            elif re.search("xpsp3", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP_SP3")
            elif re.search("xp", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP")
            elif re.search("vista", distro):
                if re.search("x64", distro):
                    try:
                        template = self.chooseTemplate(\
                            "TEMPLATE_NAME_VISTA_64")
                        if not template:
                            template = self.chooseTemplate(\
                                "TEMPLATE_NAME_VISTA")
                    except:
                        template = self.chooseTemplate("TEMPLATE_NAME_VISTA")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_VISTA")
            elif re.search("ws08", distro):
                if re.search("x64", distro):
                    if re.search("r2", distro):                        
                        template = self.chooseTemplate("TEMPLATE_NAME_WS08R2_64")
                    else:
                        template = self.chooseTemplate(\
                            "TEMPLATE_NAME_WS08_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_WS08")
            elif re.search("win7", distro):
                if re.search("x64", distro):
                    template = self.chooseTemplate("TEMPLATE_NAME_WIN7_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_WIN7")
            elif re.search("win8", distro):
                if re.search("x64", distro):
                    template = self.chooseTemplate("TEMPLATE_NAME_WIN8_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_WIN8")
            elif re.search("win10", distro):
                if re.search("x64", distro):
                    template = self.chooseTemplate("TEMPLATE_NAME_WIN10_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_WIN10")
            elif re.search("ws12", distro) and re.search("x64", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_WS12_64")
            elif re.search("debian.+", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                else:
                    r = re.search("debian(.+)", distro)
                    if arch and arch == "x86-64":
                        template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN_%s_64" %
                                                   (r.group(1).upper()))
                    else:
                        template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN_%s" %
                                               (r.group(1).upper()))
            elif re.search("debian", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN")
            elif re.search("sarge", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN_SARGE")
            elif re.search("etch", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_DEBIAN_ETCH")
            elif re.search(r"rhel5", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                else:
                    v = re.search(r"rhel(\d+)", distro).group(1)
                    if arch and arch == "x86-64":
                        template = self.chooseTemplate("TEMPLATE_NAME_RHEL_%s_64" % (v))
                    else:
                        template = self.chooseTemplate("TEMPLATE_NAME_RHEL_%s" % (v))
            elif re.search(r"rhel6", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                elif arch and arch == "x86-64":
                    template = self.chooseTemplate("TEMPLATE_NAME_RHEL_6_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_RHEL_6")
            elif re.search(r"rhelw66", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_RHEL_w66_64")
            elif re.search(r"rheld66",distro):
                template = self.chooseTemplate("TEMPLATE_NAME_RHEL_d66_64")
            elif re.search(r"rhel7", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_RHEL_7_64")
            elif re.search(r"rhel4", distro):
                v = re.search(r"rhel(\d+)", distro).group(1)
                template = self.chooseTemplate("TEMPLATE_NAME_RHEL_%s" % (v))
            elif re.search(r"fedora", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_FEDORA")
            elif re.search(r"oel5", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                else:
                    v = re.search(r"oel(\d+)", distro).group(1)
                    if arch and arch == "x86-64":
                        template = self.chooseTemplate("TEMPLATE_NAME_OEL_%s_64" % (v))
                    else:
                        template = self.chooseTemplate("TEMPLATE_NAME_OEL_%s" % (v))
            elif re.search(r"oel7", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_OEL_7_64")
            elif re.search(r"oel6", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                elif arch and arch == "x86-64":
                    template = self.chooseTemplate("TEMPLATE_NAME_OEL_6_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_OEL_6")
            elif re.search(r"centos5", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                else:
                    v = re.search(r"centos(\d+)", distro).group(1)
                    if arch and arch == "x86-64":
                        template = self.chooseTemplate("TEMPLATE_NAME_CENTOS_%s_64" % (v))
                    else:
                        template = self.chooseTemplate("TEMPLATE_NAME_CENTOS_%s" % (v))
            elif re.search(r"centos7", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_CENTOS_7_64")
            elif re.search(r"centos6", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                elif arch and arch == "x86-64":
                    template = self.chooseTemplate("TEMPLATE_NAME_CENTOS_6_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_CENTOS_6")
            elif re.search(r"centos4", distro):
                v = re.search(r"centos(\d+)", distro).group(1)
                template = self.chooseTemplate("TEMPLATE_NAME_CENTOS_%s" % (v))

            elif re.search(r"sles94", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_SLES_94")

            elif re.search(r"sles1\d+", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA") 
                else:
                    v = re.search(r"sles(\d+)", distro).group(1)
                    if arch and arch == "x86-64":
                        template = self.chooseTemplate(\
                            "TEMPLATE_NAME_SLES_%s_64" % (v))
                    else:
                        template = self.chooseTemplate("TEMPLATE_NAME_SLES_%s" % (v))
            elif re.search(r"sled\d+", distro):
                v = re.search(r"sled(\d+)", distro).group(1)
                if arch and arch == "x86-64":
                    template = self.chooseTemplate("TEMPLATE_NAME_SLED_%s_64" % (v))
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_SLED_%s" % (v))
            elif re.search(r"sl7", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_SL_7_64")
            elif re.search(r"sl\d+",distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA") 
                else:
                    v = re.search(r"sl(\d+)", distro).group(1)
                    if arch and arch == "x86-64":
                        template = self.chooseTemplate(\
                            "TEMPLATE_NAME_SL_%s_64" % (v))
                    else:
                        template = self.chooseTemplate("TEMPLATE_NAME_SL_%s"
                                                       % (v))
            elif re.search("solaris10u9-32", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_SOLARIS_10U9_32")
            elif re.search("solaris10u9", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_SOLARIS_10U9")
            elif re.search("ubuntu1004", distro):
                if arch and arch == "x86-64":
                    template = self.chooseTemplate("TEMPLATE_NAME_UBUNTU_1004_64")
                else:
                    template = self.chooseTemplate("TEMPLATE_NAME_UBUNTU_1004")
            elif re.search("ubuntu1204", distro):
                if hvm:
                    template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
                else:
                    if arch and arch == "x86-64":
                        template = self.chooseTemplate("TEMPLATE_NAME_UBUNTU_1204_64")
                    else:
                        template = self.chooseTemplate("TEMPLATE_NAME_UBUNTU_1204")
            elif re.search("ubuntu1404", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_UBUNTU_1404")
            elif re.search("ubuntudevel", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_UBUNTU_DEVEL")
            elif re.search("coreos-", distro):
                template = self.chooseTemplate("TEMPLATE_NAME_COREOS")
            elif re.search(r"other", distro):
                template = self.chooseTemplate("TEMPLATE_OTHER_MEDIA")
            else:
                raise xenrt.XRTError(\
                    "Could not identify a suitable template for %s" % (distro))
        except xenrt.XRTError, e:
            if "Could not identify a suitable template" in e.reason and \
                   (re.search(r"^fc", distro) or 
                    re.search(r"^rhel", distro) or 
                    re.search(r"^centos", distro)):
                xenrt.TEC().warning("Could not find an official template for "
                                    "%s, using a general RH one instead" %
                                    (distro))
                template = self.chooseTemplate("TEMPLATE_NAME_RHEL_5")
            else:
                raise

        return template

    def getTemplateParams(self, distro, arch):
        try:
            tname = self.getTemplate(distro=distro, arch=arch)
        except:
            xenrt.TEC().warning("Couldn't find template for %s %s" % (distro, arch))

        if tname:
            tuuid = self.minimalList("template-list", args="name-label='%s'" % tname)[0]
            defMemory = int(self.genParamGet("template", tuuid, "memory-static-max"))/xenrt.MEGA
            defVCPUs = int(self.genParamGet("template", tuuid, "VCPUs-max"))
        else:
            defMemory = None
            defVCPUs = None

        return collections.namedtuple("TemplateParams", ["defaultMemory", "defaultVCPUs"])(defMemory, defVCPUs)
        
    def isEnabled(self):
        """Return True if this host is enabled as far as xapi is concerned."""
        hml = self.getHostParam("host-metrics-live")
        en = self.getHostParam("enabled")
        return (hml == "true") and (en == "true")
        
    def guestFactory(self):
        return xenrt.lib.xenserver.guest.Guest  
        
    def allow(self, subject, role=None, useapi=False):
        """Allow this subject access to this pool"""
        # role is ignored for pre-MNR hosts
        uuid = self.getSubjectUUID(subject)
        if uuid:
            raise xenrt.XRTError("Subject %s is already present." % (subject.name))
        if useapi:
            sid = subject.getSID()
            session = self.getAPISession()
            try:
                config = {}
                config["subject_identifier"] = sid
                xenrt.TEC().logverbose("Using XenAPI to allow %s." % (subject.name.encode("utf-8")))
                session.xenapi.subject.create(config)
            finally:
                self.logoutAPISession(session)
        else:
            cli = self.getCLIInstance()
            args = []
            if subject.server.domainname:
                args.append("subject-name=%s\\\\%s" % (subject.server.domainname, subject.name))
            else:
                args.append("subject-name=%s" % (subject.name))
            cli.execute("subject-add", string.join(args)).strip()
        uuid = self.getSubjectUUID(subject)
        if not uuid:
            raise xenrt.XRTError("Failed to add %s." % (subject.name))
            
    def blockHeartbeat(self, fromHosts=None, toHosts=None, block=True,
                       ignoreErrors=False, enable=True):
        """(Un)block heartbeat traffic to/from specified hosts"""

        # The slightly nasty isinstance code in this method is because in python
        # the empty list ([]) is treated the same as None, which isn't what we
        # want here...

        if block:
            # Check if the chain exists, and if not insert it...
            if self.execdom0("iptables -L XRTheartbeatIN > /dev/null 2>&1",
                             retval="code",useThread=True) > 0:
                self.execdom0("iptables -N XRTheartbeatIN",useThread=True)
                if enable:
                    self.execdom0("iptables -I INPUT -j XRTheartbeatIN",
                                  useThread=True)
            if self.execdom0("iptables -L XRTheartbeatOUT > /dev/null 2>&1",
                             retval="code",useThread=True) > 0:
                self.execdom0("iptables -N XRTheartbeatOUT",useThread=True)
                if enable:
                    self.execdom0("iptables -I OUTPUT -j XRTheartbeatOUT",
                                  useThread=True)

        inRules = []
        outRules = []
        hbport = self.pool.haCommonConfig['UDPport']
        if not (isinstance(fromHosts, list) or isinstance(toHosts, list)):
            inRules.append("-p udp --dport %s -j DROP" % (hbport))
            outRules.append("-p udp --dport %s -j DROP" % (hbport))
            self.haHeartbeatBlocks['allfrom'] = block
            self.haHeartbeatBlocks['allto'] = block

        if isinstance(fromHosts, list):
            if len(fromHosts) == 0:
                inRules.append("-p udp --dport %s -j DROP" % (hbport))
                self.haHeartbeatBlocks['allfrom'] = block
            else:
                for h in fromHosts:
                    inRules.append("-s %s -p udp --dport %s -j DROP" %
                                   (h.getIP(),hbport))
                    if block:
                        if not h in self.haHeartbeatBlocks['from']:
                            self.haHeartbeatBlocks['from'].append(h)
                    else:
                        if h in self.haHeartbeatBlocks['from']:
                            self.haHeartbeatBlocks['from'].remove(h)

        if isinstance(toHosts, list):
            if len(toHosts) == 0:
                outRules.append("-p udp --dport %s -j DROP" % (hbport))
                self.haHeartbeatBlocks['allto'] = block
            else:
                for h in toHosts:
                    outRules.append("-d %s -p udp --dport %s -j DROP" %
                                    (h.getIP(),hbport))
                    if block:
                        if not h in self.haHeartbeatBlocks['to']:
                            self.haHeartbeatBlocks['to'].append(h)
                    else:
                        if h in self.haHeartbeatBlocks['to']:
                            self.haHeartbeatBlocks['to'].remove(h)

        cmdbase = "iptables "
        if block:
            cmdbase += "-I "
        else:
            cmdbase += "-D "
        for r in inRules:
            cmd = cmdbase
            cmd += "XRTheartbeatIN "
            cmd += r
            try:
                self.execdom0(cmd,useThread=True)
            except Exception, e:
                if not ignoreErrors:
                    raise e
        for r in outRules:
            cmd = cmdbase
            cmd += "XRTheartbeatOUT "
            cmd += r
            try:
                self.execdom0(cmd,useThread=True)
            except Exception, e:
                if not ignoreErrors:
                    raise e
                    
    def blockStatefile(self, block=True, ignoreErrors=False):
        """(Un)block statefile access"""

        # First figure out what type of SR the statefile is on
        # For now, assume we only have one statefile VDI
        srtype = self.pool.haCommonConfig['statefileType']
        if srtype == "lvmoiscsi":
            # iscsi SR, use iptables (WARNING - only works with default iscsi
            # port (3260) and blocks ALL iscsi access from the host!
            rule = "OUTPUT -p tcp --dport 3260 -j DROP"
            if block:
                cmd = "iptables -I %s" % (rule)
            else:
                cmd = "iptables -D %s" % (rule)
            try:
                self.execdom0(cmd,useThread=True)
            except Exception, e:
                if not ignoreErrors:
                    raise e
        elif srtype == "nfs":
            # nfs SR, use iptables, ports 111, 2049 and blocks ALL nfs access from the host
            rule = ("OUTPUT -p tcp --dport 111 -j DROP",
                "OUTPUT -p udp --dport 111 -j DROP", "OUTPUT -p tcp --dport 2049 -j DROP",
                "OUTPUT -p udp --dport 2049 -j DROP")
            for r in rule:
                if block:
                    cmd = "iptables -I %s" % (r)
                else:
                    cmd = "iptables -D %s" % (r)
                try:
                    self.execdom0(cmd,useThread=True)
                except Exception, e:
                    if not ignoreErrors:
                        raise e 
        elif srtype == "lvmohba":
            # FC SR, for now just use a FIST point
            try:
                self.useHAFISTPoint("sf.ioerror.sticky",block)
            except Exception, e:
                if not ignoreErrors:
                    raise e
        else:
            raise xenrt.XRTError("Statefile VDI is on %s SR, do not know "
                                 "how to (un)block this type" % (srtype))

        self.haStatefileBlocked = block
        
    def calculateBondingHash(self, mac, vlan=None):
        # Convert a mac string into an integer ID by XORing
        macbits = mac.split(":")
        id = 0 
        for m in macbits:
            id = id ^ int(m, 16)
        return id
        
    def checkReachable(self, timeout=60, level=xenrt.RC_FAIL):
        # This is a bit nasty, but if we're expecting to be off for HA, then
        # we have to claim we're reachable
        if self.pool and self.pool.haEnabled and \
           (not self.getMyHostUUID() in self.pool.haLiveset):
            return xenrt.RC_OK
        else:
            return xenrt.GenericHost.checkReachable(self, timeout=timeout, level=level)
            
    def clearMessages(self):
        """Clear all messages on the host"""
        messages = self.minimalList("message-list")
        cli = self.getCLIInstance()
        for m in messages:
            cli.execute("message-destroy", "uuid=%s" % (m))
        return messages

    def clearSubjectList(self):
        """Remove all subjects from the subject list."""
        subjects = self.minimalList("subject-list")
        cli = self.getCLIInstance()
        for subject in subjects:
            cli.execute("subject-remove", "subject-uuid=%s" % (subject))
            
    def dataSourceQuery(self, sourcename):
        """Return the value of a host data source"""
        cli = self.getCLIInstance()
        dsv = cli.execute("host-data-source-query",
                          "host=%s data-source=%s" %
                          (self.getMyHostUUID(), sourcename)).strip()
        if dsv == "nan":
            raise xenrt.XRTError(\
                "host-data-source-query/%s returned 'nan'" % (sourcename))
        return float(dsv)
  
    def disableAuthentication(self, authserver):
        cli = self.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (self.getMyHostUUID()))
        args.append("--force")
        cli.execute("host-disable-external-auth", string.join(args)).strip()
        self.resetToDefaultNetworking()

    def disableMultipathing(self, mpp_rdac=False):
        self.setHostParam("other-config:multipathing", "false")
        if mpp_rdac:
            enabled = self.execdom0('lsmod | grep mpp').strip() <> ""
            if enabled:
                self.execdom0('/opt/xensource/libexec/mpp-rdac --disable')
                self.reboot()
                
    def enableAuthentication(self, authserver, setDNS=True):
        if setDNS:
            self.setDNSServer(authserver.place.getIP())
        cli = self.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (self.getMyHostUUID()))
        args.append("auth-type=%s" % (authserver.type))
        args.append("service-name=%s" % (authserver.domainname))
        if authserver.type == "AD":
            args.append("config:domain=%s" % (authserver.domainname))
            args.append("config:user=%s" % (authserver.place.superuser))
            args.append("config:pass=%s" % (authserver.place.password))
        args.append("--force")
        cli.execute("host-enable-external-auth", string.join(args)).strip()
        
        # Using CA-33290 workaround
        if self.execdom0("test -e /opt/pbis", retval="code") == 0:
            self.execdom0("/opt/pbis/bin/lwsm set-log-level eventlog all debug")
        else:
            self.execdom0("/opt/likewise/bin/lw-set-log-level debug")
        xenrt.sleep(5)
        
    def enableIPOnPIF(self, pifuuid):
        """Enable a DHCP IP address on a non-management dom0 PIF. Takes
        a PIF UUID and returns the IP address acquired."""

        cli = self.getCLIInstance()
        cli.execute("pif-reconfigure-ip", "uuid=%s mode=dhcp" % (pifuuid))
        cli.execute("pif-plug", "uuid=%s" % (pifuuid))
        cli.execute("pif-param-set",
                    "uuid=%s disallow-unplug=true" % (pifuuid))

        # Work out the dom0 name for this interface noting that the IP
        # address goes on the bridge
        nwuuid = self.genParamGet("pif", pifuuid, "network-uuid")
        bridge = self.genParamGet("network", nwuuid, "bridge")

        # Wait a while for DHCP then verify
        xenrt.sleep(60)
        data = self.execdom0("ifconfig %s" % (bridge))
        if not re.search(r"UP", data):
            raise xenrt.XRTFailure("New interface not UP after configuration")
        try:
            ip = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data).group("ip")
        except:
            raise xenrt.XRTFailure("No IP address found for new interface")

        return ip
    
    def deny(self, subject):
        uuid = self.getSubjectUUID(subject)
        if not uuid:
            raise xenrt.XRTError("Can't remove user who isn't present. (%s)" % 
                                 (subject.name))
        cli = self.getCLIInstance()
        args = []
        args.append("subject-uuid=%s" % (uuid))
        cli.execute("subject-remove", string.join(args)).strip()
        uuid = self.getSubjectUUID(subject)
        if uuid:
            raise xenrt.XRTError("Failed to remove %s." % (subject.name))
            
    def enableMultipathing(self, handle="dmp", mpp_rdac=False):
        self.setHostParam("other-config:multipathing", "true")
        self.setHostParam("other-config:multipathhandle", handle)
        if mpp_rdac:
            try:
                enabled = self.execdom0('lsmod | grep mpp').strip() <> ""
            except:
                enabled = False
            if not enabled:
                self.execdom0('/opt/xensource/libexec/mpp-rdac --enable')
                self.reboot()
    
        
    def getIPAddressOfSecondaryInterface(self, assumedid):
        """Returns the IP address of a non-management dom0 interface. Takes
        the assumed enumeration index for the interface. Raises an
        error exception if the interface does not have an address."""
        # Look up the product's enumeration name for this interface
        eth = self.getSecondaryNIC(assumedid)

        try:
            data = self.execdom0("ifconfig %s" %
                                 (string.replace(eth, "eth", "xenbr")))
        except:
            raise xenrt.XRTError("Interface not configured for IP")
        if not re.search(r"UP", data):
            raise xenrt.XRTFailure("Interface not UP")
        try:
            ip = re.search(".*inet (addr:)?(?P<ip>[0-9\.]+)", data).group("ip")
        except:
            raise xenrt.XRTFailure("No IP address found for interface")

        return ip

    def getMessages(self, ignoreMessages=None, messageName=None):
        """Retrieve all messages from the host"""
        args = []
        if messageName:
            args.append("name=\"%s\"" % (messageName))
        messages = self.minimalList("message-list", args=string.join(args))
        if ignoreMessages:
            messages = [m for m in messages if m not in ignoreMessages]

        messagesWithContents = []
        for m in messages:
            message = {'uuid':m}
            for p in ["name","priority","class","obj-uuid","timestamp","body"]:
                message[p] = self.genParamGet("message", m, p)
            messagesWithContents.append(message)

        return messagesWithContents
    
    def getMultipathCounts(self, pbd, id):
        """Returns a list of [current, total, last changed, last count] for
           the specified device id on the specified pbd"""
        data = self.genParamGet("pbd", pbd, "other-config", "mpath-%s" % (id))
        return eval(data)        
        
    def getMultipathInfo(self,onlyActive=False,useLL=False):
        # Note the useLL parameter is now deprecated and was used when we
        # retrieved status info using the multipath command rather than the CLI
        mp = self.execdom0("echo show topology | multipathd -k || true",
                           timeout=300)
        mpdevs = {}
        mpdev = None
        for line in mp.splitlines():
            r = re.search(r"([0-9A-Za-z-_]+) *dm-\d+", line)
            if r:
                mpdev = r.group(1)
                mpdevs[mpdev] = []
                continue
            r = re.search(r"^ \\_ \S+\s+(\S+)[^[]+\[([^\]]+)\]\[([^\]]+)\]", 
                          line)
            if not r:
                r = re.search(r"^[| ] [|`]- \S+\s+(\S+)\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)", 
                              line)
            failedStates = ["failed", "faulty"] # May need to add 'shaky'
            if r and mpdev and (not onlyActive or not (\
               (r.group(2) in failedStates) or (r.group(3) in failedStates))):
                mpdevs[mpdev].append(r.group(1))

        return mpdevs
        
    def getMultipathInfoMPP(self, onlyActive=False):
        mpdevs = {}
        mppaths = {}
        try:
            devs = self.execdom0("ls -l /dev/disk/by-mpp").strip().splitlines()[1:]
            for dev in devs:
                x = dev.split(' ')
                mpdevs[x[-3]] = x[-1].split('/')[-1]

            for scsiid in mpdevs.keys():
                status = self.execdom0("/opt/xensource/sm/mpp_mpathutil.py pathinfo %s Status" % scsiid).strip()
                if status == '':
                    del mpdevs[scsiid]
                else:
                    if onlyActive:
                        r = re.search(r".*PATHS UP: (\d+).*", status)
                    else:
                        r = re.search(r".*TOTAL PATHS: (\d+).*", status)
                    if r:
                        mppaths[scsiid] = int(r.group(1))
        except:
            pass
        return mpdevs, mppaths
        
    def getSRMaster(self, sruuid):
        """Return the host object for the host that is the SR master for the
        specified SR UUID"""
        if self.genParamGet("sr", sruuid, "shared") == "true":
            # Assume the pool master is the SR master for a shared SR
            if self.pool:
                return self.pool.master
            return self
        # The SR master of a local SR is the host the SR belongs to
        hostuuids = self.minimalList("pbd-list",
                                     "host-uuid",
                                     "sr-uuid=%s" % (sruuid))
        if len(hostuuids) == 0:
            raise xenrt.XRTError("Could not find a PBD for SR", sruuid)
        if len(hostuuids) > 1:
            raise xenrt.XRTError("More than one PBD found for non-shared SR",
                                 sruuid)
        if self.pool:
            host = self.pool.getHost(hostuuids[0])
            if host:
                return host
            raise xenrt.XRTError("Could not find host by UUID for SR master",
                                 hostuuids[0])
        if self.getMyHostUUID() == hostuuids[0]:
            return self
        raise xenrt.XRTError("Standalone host UUID does not match SR master "
                             "PBD host UUID", hostuuids[0])
                             
    def getSubjectSID(self, subject):
        if isinstance(subject, xenrt.PAMServer.Subject):
            if str(subject) == "user":
                return "u%s" % (self.execdom0("id -u %s" % (subject.name)).strip())
            else:
                return "g%s" % (self.execdom0("cat /etc/group | grep %s | cut -d ':' -f 3" % (subject.name)).strip())
        else:
            cli = self.getCLIInstance()
            auth_type = cli.execute('host-param-get', 'param-name=external-auth-type uuid=%s' % self.getMyHostUUID()).strip()
            is_opt_pbis_exists = self.execdom0("test -e /opt/pbis", retval="code") == 0
            if (auth_type == "AD") and (is_opt_pbis_exists):
                s = self.execdom0("/opt/pbis/bin/find-%s-by-name %s\\\\%s" % 
                                  (subject, 
                                   subject.server.domainname.encode("utf-8"), 
                                   subject.name.encode("utf-8"))).strip()
            else:
                s = self.execdom0("/opt/likewise/bin/lw-find-%s-by-name %s\\\\%s" % 
                                  (subject, 
                                   subject.server.domainname.encode("utf-8"), 
                                   subject.name.encode("utf-8"))).strip()
            return re.search("SID:\s+(?P<sid>.*)", s).group("sid")

    def getSubjectUUID(self, subject):
        sid = subject.getSID()
        return self.parseListForUUID("subject-list", "subject-identifier", sid)
        
    def getTestHotfix(self, hotfixNumber):
        workdir = xenrt.TEC().getWorkdir()
        if xenrt.command("test -e %s/patchapply" % workdir, retval="code") != 0:
            xenrt.getTestTarball("patchapply", extract=True, directory=workdir)
        
        if self.productVersion == "Orlando":
            return "%s/patchapply/hotfix-orlando5-test%u.xsupdate" % (workdir, hotfixNumber)
        else:
            return "%s/patchapply/hotfix-george-test%u.xsupdate" % (workdir, hotfixNumber)

    def getVDIPhysicalSizeAndType(self, vdiuuid):
        """Return a pair of (physical size in bytes, type) for the VDI. Type
        is "VHD" or "LV"."""
        sr = self.genParamGet("vdi", vdiuuid, "sr-uuid")
        srtype = self.genParamGet("sr", sr, "type")
        host = self.getSRMaster(sr)
        host.execdom0("xe sr-scan uuid=%s" % sr)
        foundsize = 0
        if srtype in ["ext", "nfs"]:
            path = "/var/run/sr-mount/%s/%s.vhd" % (sr, vdiuuid)
            if host.execdom0("test -e %s" % (path), retval="code") != 0:
                raise xenrt.XRTFailure("VDI missing", vdiuuid)
            foundtype = "VHD"
            foundsize = int(host.execdom0("stat -c %s " + path).strip())
        elif srtype in ["lvm", "lvmoiscsi", "lvmohba"]:
            vpath = "VG_XenStorage-%s/VHD-%s" % (sr, vdiuuid)
            lpath = "VG_XenStorage-%s/LV-%s" % (sr, vdiuuid)
            if host.execRawStorageCommand(sr, "lvdisplay %s" % (vpath), retval="code") == 0:
                foundtype = "VHD"
                foundsize = int(host.execRawStorageCommand(sr,
                    "lvdisplay -c %s 2> /dev/null" % (vpath)).split(":")[6]) * 512
            elif host.execRawStorageCommand(sr, "lvdisplay %s" % (lpath), retval="code") == 0:
                foundtype = "LV"
                foundsize = int(host.execRawStorageCommand(sr,
                    "lvdisplay -c %s 2> /dev/null" % (lpath)).split(":")[6]) * 512
            else:
                raise xenrt.XRTFailure("VDI missing", vdiuuid)
        elif srtype in ["rawhba"]:
            scsid = self.genParamGet("vdi", vdiuuid, "name-label").strip() # only in rawhba sr-type.
            devices = host.execdom0("ls -ltr /dev/disk/by-scsid/%s/sd*; exit 0" % (scsid))
            devices = devices.splitlines()
            sizeList = []
            for device in devices:
                tmp = device.split("/")[-1] # check all block devices has the same size.
                blockSize = int(host.execdom0("cat /sys/block/%s/size; exit 0" % (tmp)))
                sizeList.append(blockSize)
            if  len(set(sizeList)) == 1: # all block devices reported same size.
                foundsize = sizeList[0] * 512
                foundtype = "RAW"
            else:
                raise xenrt.XRTError("The list of block devices representing the same LUN has varying disk size.")
        else:
            raise xenrt.XRTError("VDI type/size check unimplemented for %s" %
                                 (srtype))
        return foundsize, foundtype
        
    def getXSConsoleInstance(self):
        return xenrt.lib.xenserver.xsconsole.getInstance(self)

    def listVHDsInSR(self, sruuid):
        """Return a list of VHD UUIDs in the SR"""
        srtype = self.genParamGet("sr", sruuid, "type")
        host = self.getSRMaster(sruuid)
        if srtype in ["ext", "nfs"]:
            path = "/var/run/sr-mount/%s" % (sruuid)
            data = host.execdom0("ls %s" % (path))
            return re.findall(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                              "[0-9a-f]{4}-[0-9a-f]{12}).vhd", data)
        elif srtype in ["lvm", "lvmoiscsi", "lvmohba"]:
            path = "VG_XenStorage-%s" % (sruuid)
            data = host.execRawStorageCommand(sruuid, "lvs --noheadings -o lv_name %s" % (path))
            return re.findall(\
                r"(?:VHD|LV)-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                "[0-9a-f]{4}-[0-9a-f]{12})", data)
        else:
            raise xenrt.XRTError("listVHDs unimplemented for %s" % (srtype))

    def logout(self, subject):
        xenrt.TEC().logverbose("Logging out all sessions associated "
                               "with %s." % (subject.name))
        sid = self.getSubjectSID(subject)
        cli = self.getCLIInstance()
        args = []
        args.append("subject-identifier=%s" % (sid))
        cli.execute("session-subject-identifier-logout", string.join(args))
        if sid in self.minimalList("session-subject-identifier-list"):
            raise xenrt.XRTError("All sessions not logged out.")

    def logoutAll(self):
        xenrt.TEC().logverbose("Logging out all sessions.")
        cli = self.getCLIInstance()
        cli.execute("session-subject-identifier-logout-all")
        sids = self.minimalList("session-subject-identifier-list")
        if sids: raise xenrt.XRTError("Sessions still logged in: %s" % (sids))
        
    def messageCreate(self, name, body, priority=1):
        self.messageGeneralCreate("host",
                                  self.getMyHostUUID(),
                                  name,
                                  body,
                                  priority) 

    def messageGeneralCreate(self, etype, uuid, name, body, priority=1):
        """Create an event/alert message."""
        cli = self.getCLIInstance()
        args = []
        args.append("%s-uuid=%s" % (etype, uuid))
        args.append("name=\"%s\"" % (name))
        args.append("body=\"%s\"" % (body))
        args.append("priority=%u" % (priority))
        cli.execute("message-create", string.join(args)).strip()
        
    def parseLocalHAConfig(self, dom):
        config = {}
        try:
            lc = dom.getElementsByTagName("local-config")[0]
            lh = lc.getElementsByTagName("localhost")[0]
            for n in lh.childNodes:
                if n.nodeName != "#text":
                    config[n.nodeName] = n.childNodes[0].data.strip()
        except Exception, e:
            raise xenrt.XRTError("Exception while parsing HA XML config file" +
                                 str(e))

        self.haLocalConfig = config
        
    def postInstall(self):
        """Perform any product-specific post install actions."""
        # If this machine has a specifed network to use for iSCSI then
        # make sure this interface has an IP address. We currently do
        # this regardless of whether we will actually use iSCSI in this
        # test. An alternative mechanism to to force all interfaces
        # to be given IP addresses using FORCE_IP_ALL and 
        # relying on resource configurations.
        fnw = self.lookup("FORCE_ISCSI_NETWORK", None)
        if fnw:
            # Check we have an interface on this network
            nics = self.listSecondaryNICs(fnw)
            if len(nics) == 0:
                raise xenrt.XRTError("Forced to use iSCSI network %s "
                                     "but %s does not have it" %
                                     (fnw, self.getName()))
                
            # See if any interface on this network is configured
            configured = False
            for nic in nics:
                try:
                    ip = self.getIPAddressOfSecondaryInterface(nic)
                    configured = True
                except:
                    pass

            if not configured:
                # Configure the first one we found
                self.setIPAddressOnSecondaryInterface(nics[0])
        if self.lookup("FORCE_IP_ALL", False, boolean=True):
            for nic in self.listSecondaryNICs():
                try:
                    ip = self.getIPAddressOfSecondaryInterface(nic)
                except:
                    self.setIPAddressOnSecondaryInterface(nic)

        xenTrace = xenrt.TEC().lookup("OPTION_XENTRACE", None)
        if xenTrace:
            # Use xentrace to capture traces on VM crash
            try:
                bufferSize = int(xenTrace)
            except:
                # Default to 64M
                bufferSize = 64

            script = """#!/bin/bash
mkdir -p /tmp/xenrt-xentrace
while [ `df /tmp | grep -v Filesystem | awk '{print $4}'` -gt 512000 ]; do
    rm -f /tmp/crash.trace || true
    xentrace -D -e all -s 5000 -M %sM /tmp/crash.trace &
    xe event-wait class=vm power-state=paused
    killall -INT xentrace
    gzip /tmp/crash.trace
    mv /tmp/crash.trace.gz /tmp/xenrt-xentrace/crash.trace.`date +%%Y%%m%%d%%k%%M%%S`.gz
    domids=`list_domains | awk -F \| {'print $1'}`
    for d in $domids; do
        /usr/lib/xen/bin/xenctx --stack-trace $d > /tmp/xenrt-xentrace/domid$d.xenctx
    done
done
logger "Stopping xentrace loop, host has less than 512M disk space free"

""" % (bufferSize)

            tmpfile = xenrt.TEC().tempFile()
            f = file(tmpfile, "w")
            f.write(script)
            f.close()
            sftp = self.sftpClient()
            try:
                sftp.copyTo(tmpfile, "/etc/xenrt-xentrace.sh")
            finally:
                sftp.close()
            if self.execdom0("grep -q xenrt-xentrace\\.sh /etc/rc.d/rc.local",
                             retval="code") != 0:
                self.execdom0("echo 'nohup /etc/xenrt-xentrace.sh > /dev/null "
                              "2>&1 < /dev/null &' >> /etc/rc.d/rc.local")
            if self.execdom0("ps axfww | grep -q xenrt-xentrace\\.sh ",
                             retval="code") != 0:
                self.execdom0("nohup /etc/xenrt-xentrace.sh > /dev/null "
                              "2>&1 < /dev/null &")
            xenrt.TEC().logverbose("Enabled xentrace crash catcher with %sM "
                                   "buffer" % (bufferSize))
        # Check we have a default SR (unless in diskless mode).
        if not xenrt.TEC().lookup("OPTION_NO_DISK_CLAIM",
                                  False,
                                  boolean=True):
            sruuid = self.lookupDefaultSR()
            xenrt.TEC().logverbose("Default SR: %s" % (sruuid))
            scheduler = xenrt.TEC().lookup("DISK_SCHEDULER", "cfq") 
            pbds = self.minimalList("pbd-list", args="sr-uuid=%s" % (sruuid))
            if not scheduler == "cfq": 
                cli = self.getCLIInstance()
                self.genParamSet("sr", sruuid, "other-config:scheduler", scheduler)
                for p in pbds:
                    cli.execute("pbd-unplug", "uuid=%s" % (p))
                    cli.execute("pbd-plug", "uuid=%s" % (p))
            try:
                for p in pbds:
                    device = self.genParamGet("pbd", p, "device-config", pkey="device")
                    devicename = self.execdom0("readlink -f %s" % (device)).strip()
                    if devicename.startswith("/dev/"):
                        devicename = xenrt.extractDevice(devicename[5:],
                                                         sysblock=True)
                    data = self.execdom0("cat /sys/block/%s/queue/scheduler" % (devicename)).strip()
                    if not re.search("\[%s\]" % (scheduler), data):
                        xenrt.TEC().logverbose("Unexpected scheduler information: Expected %s Got %s" % (scheduler, data))
            except: 
                pass

        if xenrt.TEC().lookup("WORKAROUND_SCTX-463", False, boolean=True):
            pcount = int(self.execdom0("grep -c processor /proc/cpuinfo").strip())


            # Check that this is a 5.6.0 host (we don't want to install to older hosts)
            if not isinstance(self, xenrt.lib.xenserver.MNRHost):
                xenrt.TEC().logverbose("Not applying multi CPU patch to non-MNR host")
            elif pcount == 1:            
                # Apply the dom0 multi-vcpu workaround
                xenrt.TEC().comment("Enabling multiple vCPUS on dom0...")
                fn = xenrt.TEC().getFile("/usr/groups/xen/abrett/multi-vcpu-dom0_010910.tar")
                sftp = self.sftpClient()
                try:
                    sftp.copyTo(fn, "/root/multi-vcpu-dom0.tar")
                finally:
                    sftp.close()       
                self.execdom0("cd /root; tar -xf multi-vcpu-dom0.tar")
                self.execdom0("cd /root/multi-vcpu; ./install.sh")
                self.reboot()
                xenrt.TEC().logverbose("Multi vcpu enablement complete")
            else:
                xenrt.TEC().logverbose("Not enabling multiple vCPUs as there are already %u" % (pcount))

        if xenrt.TEC().lookup("ENABLE_MULTICAST", False, boolean=True):
            if isinstance(self, xenrt.lib.xenserver.DundeeHost):
                self.execdom0("sed -i '/multicast off/d' /usr/libexec/xenopsd/vif-real")
            else:
                self.execdom0("sed -i '/multicast off/d' /etc/xensource/scripts/vif")

    def postUpgrade(self):
        """Perform any product-specific post upgrade actions."""

        if self.pool and self.pool.rollingUpgradeInProgress:
            # Perform any steps required on each host as part of rolling upgrade
            pass
        else:
            # Perform any steps required to upgrade this host standalone or
            # after rolling upgrade

            # If we have upgraded to a version with LVHD then upgrade
            # all LVM based SRs. This should be safe even if the SRs are
            # already upgraded.
            if self.productVersion == 'George':
                if xenrt.TEC().lookup("AUTO_UPGRADE_SRS", True, boolean=True):
                    xenrt.TEC().logverbose("Upgrading any LVM SRs to LVHD")
                    for srtype in ["lvm", "lvmohba", "lvmoiscsi"]:
                        srs = self.getSRs(type=srtype)
                        for sr in srs:
                            xenrt.TEC().logverbose("Upgrading SR %s (%s) on %s" %
                                                   (sr, srtype, self.getName()))
                            self.execdom0("/opt/xensource/bin/xe-lvm-upgrade %s" %
                                          sr)
        
    def removeDNSServer(self, server):
        resolvconf = self.execdom0("readlink -f /etc/resolv.conf").strip()
        self.execdom0(r"sed -i '/nameserver %s/d' %s" % (server, resolvconf))
        self.execdom0(r"sed -i 's/;nameserver/nameserver/g' %s" % (resolvconf))
        self.execdom0("rm -f /etc/dhclient.conf")
        self.execdom0("if [ -e /etc/dhclient.conf.xenrt ]; then "
                      "  mv /etc/dhclient.conf.xenrt /etc/dhclient.conf; fi")
        xenrt.sleep(300)

    def removeIPAddressFromSecondaryInterface(self, assumedid):
        """Remove an IP configuration from a non-management dom0 network
        interface. Takes the assumed enumeration index for the interface."""
        # Look up the product's enumeration name for this interface
        eth = self.getSecondaryNIC(assumedid)

        # Find the PIF UUID and set the IP details
        pifuuid = self.getPIFUUID(eth)
        self.removeIPFromPIF(pifuuid)
        
    def removeIPFromPIF(self, pifuuid):
        """Remove an IP configuration from a non-management dom0 network
        interface."""
        cli = self.getCLIInstance()
        cli.execute("pif-reconfigure-ip", "uuid=%s mode=none" % (pifuuid))
        cli.execute("pif-param-set",
                    "uuid=%s disallow-unplug=false" % (pifuuid))
        cli.execute("pif-unplug", "uuid=%s" % (pifuuid))

        # Work out the dom0 name for this interface noting that the IP
        # address goes on the bridge
        nwuuid = self.genParamGet("pif", pifuuid, "network-uuid")
        bridge = self.genParamGet("network", nwuuid, "bridge")

        # Wait a while for cleanup then verify
        xenrt.sleep(60)
        try:
            data = self.execdom0("ifconfig %s" % (bridge))
        except:
            # A failure is good because that means the bridge has been
            # cleaned up
            data = ""
        if re.search(r"UP", data):
            raise xenrt.XRTFailure("Interface UP after IP removal")
            
    def resetHeartbeatBlocks(self):
        """Clear out any heartbeat blocks that are in place"""
        self.execdom0("iptables -F XRTheartbeatIN > /dev/null 2>&1 || true",
                      useThread=True)
        self.execdom0("iptables -F XRTheartbeatOUT > /dev/null 2>&1 || true",
                      useThread=True)
        self.haHeartbeatBlocks = {'allto': False, 'to': [], 'allfrom': False,
                                  'from': []}
                                  
    # Kirkwood / WLB related methods
    def retrieveWLBEvacuateRecommendations(self):
        cli = self.getCLIInstance()
        data = cli.execute("host-retrieve-wlb-evacuate-recommendations",
                           "uuid=%s" % (self.getMyHostUUID()))
        return xenrt.util.strlistToDict(data.splitlines()[1:], sep=":", keyonly=False)    
        
    def setDNSServer(self, server):
        cli = self.getCLIInstance()
        pifuuid = self.minimalList("pif-list",args="host-uuid=%s management=true" % (self.getMyHostUUID()))[0]
        ip = self.genParamGet("pif",pifuuid,"IP")
        netmask = self.genParamGet("pif",pifuuid,"netmask")
        # For some reason the gateway doesn't seem to get written to the DB
        d = os.popen("ip route show dev eth0").read()
        try:
            gateway = re.search("default via ([\d+\.]+)", d).group(1)
        except:
            gateway = None
        args = []
        args.append("uuid=%s" % (pifuuid))
        args.append("mode=static")
        args.append("ip=%s" % (ip))
        args.append("dns=%s" % (server))
        args.append("gateway=%s" % (gateway))
        args.append("netmask=%s" % (netmask))
        try:
            cli.execute("pif-reconfigure-ip", string.join(args))
        except xenrt.XRTException, e:
            if e.data and (("Lost connection to the server." in e.data) or
                           ("You attempted an operation which involves a host which could not be contacted." in e.data)):
                pass
            else:
                raise
        xenrt.sleep(5) # give the server a few seconds to update resolv.conf
    
    def resetToDefaultNetworking(self):
        cli = self.getCLIInstance()
        pifuuid = self.minimalList("pif-list",args="host-uuid=%s management=true" % (self.getMyHostUUID()))[0]
        args = []
        args.append("uuid=%s" % (pifuuid))
        args.append("mode=dhcp")
        try:
            cli.execute("pif-reconfigure-ip", string.join(args))
        except xenrt.XRTException, e:
            if e.data and re.search("Lost connection to the server.", e.data):
                pass
            else:
                raise
        xenrt.sleep(60) # give the server a few seconds to update resolv.conf

    def setIPAddressOnSecondaryInterface(self, assumedid):
        """Enable a DHCP IP address on a non-management dom0 network
        interface. This is used for storage traffic for example. Takes
        the assumed enumeration index for the interface and returns the
        IP address the interfaces gets."""
        
        # Look up the product's enumeration name for this interface
        if assumedid == 0:
            eth = self.getDefaultInterface()
        else:
            eth = self.getSecondaryNIC(assumedid)

        # Find the PIF UUID and set the IP details
        pifuuid = self.getPIFUUID(eth)
        return self.enableIPOnPIF(pifuuid)

    def getHAPath(self):
        return "/opt/xensource/xha"
        
    def useHAFISTPoint(self, point, enable=True):
        cmd = "PATH=$PATH:%s %s/calldaemon fist" % (self.getHAPath(), self.getHAPath())
        if enable:
            cmd += " enable "
        else:
            cmd += " disable "
        cmd += point
        self.execdom0(cmd)
        
    def vhdExists(self, vdiuuid, sruuid):
        """Return true if the (L)VHD file/volume exists in this SR."""
        srtype = self.genParamGet("sr", sruuid, "type")
        host = self.getSRMaster(sruuid)
        if srtype in ["ext", "nfs"]:
            path = "/var/run/sr-mount/%s/%s.vhd" % (sruuid, vdiuuid)
            if host.execdom0("test -e %s" % (path), retval="code") == 0:
                return True
            return False
        elif srtype in ["lvm", "lvmoiscsi", "lvmohba"]:
            path = "VG_XenStorage-%s/VHD-%s" % (sruuid, vdiuuid)
            if host.execRawStorageCommand(sruuid, "lvdisplay %s" % (path), retval="code") == 0:
                return True
            path = "VG_XenStorage-%s/LV-%s" % (sruuid, vdiuuid)
            if host.execRawStorageCommand(sruuid, "lvdisplay %s" % (path), retval="code") == 0:
                return True
            return False
        else:
            raise xenrt.XRTError("vhdExists unimplemented for %s" % (srtype))
            
    def vhdQueryParent(self, vdiuuid):
        """Return the VHD UUID (or None) of the parent of this VHD/LV.
        The vdiuuid may be a leaf or hidden base copy VDI."""
        sr = self.genParamGet("vdi", vdiuuid, "sr-uuid")
        srtype = self.genParamGet("sr", sr, "type")
        host = self.getSRMaster(sr)
        islvhd = False
        if srtype in ["ext", "nfs"]:
            path = "/var/run/sr-mount/%s/%s.vhd" % (sr, vdiuuid)
        elif srtype in ["lvm", "lvmoiscsi", "lvmohba"]:
            lvpath = "/dev/VG_XenStorage-%s/LV-%s" % (sr, vdiuuid)
            if host.execRawStorageCommand(sr, "lvdisplay %s" % (lvpath), retval="code") == 0:
                # This is a raw LV VDI with no parent
                return None

            # TODO find a way to do this with vhd-util or similar that
            # does not get into a big LVM volume activation mess (non-
            # working code commented out below)
            try:
                v = self.genParamGet("vdi",
                                     vdiuuid,
                                     "sm-config",
                                     "vhd-parent")
            except:
                return None
            return v
        
            #path = "/dev/VG_XenStorage-%s/VHD-%s" % (sr, vdiuuid)
            #islvhd = True
        else:
            raise xenrt.XRTError("vhdQueryParent unimplemented for %s" %
                                 (srtype))
        #needsDeactivating = False
        #if islvhd:
        #    # If the LVHD volume is not in use we may have to activate it
        #    # to query the volume. This is racey - beware.
        #    ldata = host.execdom0("lvdisplay %s" % (path))
        #    if "NOT available" in ldata:
        #        xenrt.TEC().logverbose("Activating LVM volume before running "
        #                               "vhd-util")
        #        host.execdom0("lvchange -ay %s" % (path))
        #        needsDeactivating = True
        try:
            data = host.execdom0("vhd-util query -n %s -p" % (path))
        finally:
            pass
            #if needsDeactivating:
            #    host.execdom0("lvchange -an %s" % (path))
        if re.search(r"has no parent", data):
            return None
        r = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                      "[0-9a-f]{4}-[0-9a-f]{12})\.vhd", data)
        if r:
            return r.group(1)
        raise xenrt.XRTError("Could not parse vhd-util output", data)
        
    def vhdSRDisplayDebug(self, sruuid):
        """Log a debug dump of the SR's VHD structures"""
        host = self.getSRMaster(sruuid)
        xenrt.TEC().logverbose("Debug dump of SR %s VHD structure:" % (sruuid))
        srtype = self.genParamGet("sr", sruuid, "type")
        if srtype in ["ext", "nfs"]:
            path = "/var/run/sr-mount/%s/*.vhd" % (sruuid)
            try:
                host.execdom0("vhd-util scan -p -f %s" % (path))
            except:
                pass
        elif srtype in ["lvm", "lvmoiscsi", "lvmohba"]:
            path = "VG_XenStorage-%s" % (sruuid)
            try:
                host.execdom0(\
                    "vhd-util scan -f -m 'VHD-*' -l %s -p" % (path))
            except:
                pass
            try:
                host.execdom0(\
                    "vhd-util scan -f -m 'LV-*' -l %s -p" % (path))
            except:
                pass
        else:
            xenrt.TEC().warning("vhdSRDisplayDebug not implemented for %s" %
                                (srtype))
                                
    def resetToFreshInstall(self, setupISOs=False):
        """Resets the host state to that similar to a fresh installation."""
        # We have to deal with HA carefully here, otherwise the host will fence
        script = """#!/bin/bash

set -x

# Disable HA if it's running
%s/ha_set_pool_state invalid || true
%s/ha_disarm_fencing || true
%s/ha_stop_daemon || true

# Just in case hypervisor watchdogs are left behind
/opt/xensource/debug/xenops watchdog -slot 1 -timeout 0
/opt/xensource/debug/xenops watchdog -slot 2 -timeout 0

# Remove static VDIs etc
/etc/init.d/xapi stop || true
rm -rf /etc/xensource/static-vdis || true
mkdir -p /etc/xensource/static-vdis
rm -f /etc/xensource/xhad.conf || true

""" % (self.getHAPath(), self.getHAPath(), self.getHAPath())
        tmpfile = xenrt.TEC().tempFile()
        f = file(tmpfile, "w")
        f.write(script)
        f.close()
        sftp = self.sftpClient()
        sftp.copyTo(tmpfile, "/tmp/xenrt_ha_reset.sh")
        sftp.close()

        self.execdom0("chmod a+x /tmp/xenrt_ha_reset.sh")
        self.execdom0("PATH=$PATH:%s "
                      "/tmp/xenrt_ha_reset.sh" % (self.getHAPath()),
                      level=xenrt.RC_OK,
                      getreply=False)

        # Remove any NFS blocks
        if self.isCentOS7Dom0():
            self.execdom0("chkconfig --del blocknfs || true")
        else:
            self.execdom0("rm -f /etc/rc3.d/S09blocknfs || true")

        # Do the normal reset procedure
        try:
            xenrt.TEC().logverbose("Trying to remove DVSC. (%s)" % (self.controller))
            self.disassociateDVS()
        except Exception, e: 
            xenrt.TEC().logverbose("Failed to disassociate DVSC. (%s)" % (str(e)))

        defstorage = None
        if self.execdom0("test -e /opt/xensource/libexec/revert-to-factory",
                         retval="code") == 0:
            if self.execdom0(\
                "test -e /etc/firstboot.d/data/default-storage.conf",
                retval="code") == 0:
                defstorage = self.execdom0(\
                    "cat /etc/firstboot.d/data/default-storage.conf")
            # XRT-4338 Workaround the poor error handling of the script
            self.execdom0("if [ -d /.flash ]; then "
                          "  touch /.flash/rt-XRT-4338; fi")
            self.execdom0("/opt/xensource/libexec/revert-to-factory yesimeanit")
            # Don't do this on HDD edition otherwise we've lost the product too
            if self.execdom0("grep -q '7 /.state' /proc/mounts",
                             retval="code") != 0:
                self.cleanLocalDisks()
        else:
            self.execdom0("/etc/init.d/xapi stop || true")
            self.execdom0("rm -f /etc/firstboot.d/state/*")
            self.execdom0("echo -n master > /etc/xensource/pool.conf")
            self.execdom0("rm -f /etc/xensource/ptoken")
            self.execdom0("rm -f /etc/xensource/xapi-ssl.pem")
            # stablize ovs which might panic due to the missing of xapi cert
            xenrt.sleep(30)
            self.execdom0("rm -f /var/xapi/state.db*")
            self.execdom0("rm -f /var/xapi/local.db*")
            self.execdom0("rm -f /var/xapi/ha_metadata.db*")
            self.execdom0("rm -f /etc/xensource/xapi_block_startup || true")
            self.execdom0("rm -f /etc/xensource-inventory.prev")
            # Clear up any static VDIs (this will fail if one is mounted, but should still remove the config)
            self.execdom0("rm -rf /etc/xensource/static-vdis/* || true")
            self.execdom0("mv /etc/xensource-inventory "
                          "/etc/xensource-inventory.prev")
            self.execdom0("cat /etc/xensource-inventory.prev | "
                          "grep -v INSTALLATION_UUID | "
                          "grep -v CONTROL_DOMAIN_UUID | "
                          "grep -v HA_INTERFACES > "
                          "/etc/xensource-inventory")
            self.execdom0("echo INSTALLATION_UUID=\\'$(uuidgen)\\' >> "
                          "/etc/xensource-inventory")
            self.execdom0("echo CONTROL_DOMAIN_UUID=\\'$(uuidgen)\\' >> "
                          "/etc/xensource-inventory")
                        
            try:
                self.execdom0("if [ -e /etc/multipath-disabled.conf ]; then "
                              "  rm -f /etc/multipath.conf;"
                              "  ln -s /etc/multipath-disabled.conf "
                              "     /etc/multipath.conf ; fi ")
            except:
                pass

        # Make an attempt at clearing out logs
        try:
            self.execdom0("service syslog stop || true")
            self.execdom0("rm -f /var/log/messages* || true")
            self.execdom0("touch /var/log/messages")
            self.execdom0("rm -f /var/log/xensource* || true")
            self.execdom0("touch /var/log/xensource")
            self.execdom0("rm -rf /var/log/xen/* || true")
            self.execdom0("rm -f /var/log/xha*")
            self.execdom0("mv -f /var/crash /var/crash_`date +%d%m%Y-%H%M%S` || true")
            self.execdom0("mkdir -p /var/crash")
        except:
            xenrt.TEC().logverbose("Exception while cleaning up logs in resetToFreshInstall")

        # Delete any fist points that exist
        self.execdom0("rm -f /tmp/fist_*")

        # Do a sync to flush buffers etc
        self.execdom0("sync")
        xenrt.sleep(5)

        self._clearObjectCache()
        self.pool = None
        self.guests = {}
        xenrt.TEC().logverbose("Rebooting host using sysrq 'b' to avoid "
                               "a soft-reboot hang breaking tests")
        self.reboot(sleeptime=180,forced=True)

        # Workaround the revert-to-factory on HDD bug
        if xenrt.TEC().lookup("WORKAROUND_CA26304", False, boolean=True) and \
               defstorage:
            if self.execdom0(\
                "test -e /etc/firstboot.d/data/default-storage.conf",
                retval="code") != 0:
                xenrt.TEC().warning("Using CA-26304 workaround")
                tmpdffile = xenrt.TEC().tempFile()
                f = file(tmpdffile, "w")
                f.write(defstorage)
                f.close()
                sftp = self.sftpClient()
                try:
                    sftp.copyTo(tmpdffile,
                                "/etc/firstboot.d/data/default-storage.conf")
                finally:
                    sftp.close()
                self.execdom0("rm -f /etc/firstboot.d/state/10-prepare-storage"
                              " /etc/firstboot.d/state/15-set-default-storage")
                self.reboot()

        # Reset out host name on embedded builds
        self.setHostParam("name-label", self.getName())

        # Re-apply the license in case the cleanup removed it
        license = xenrt.TEC().lookup("OPTION_APPLY_LICENSE",
                                     True,
                                     boolean=True)
        if license:
            self.license()
            
        if setupISOs:
            # Do ISO imports
            devices = [xenrt.TEC().lookup("EXPORT_ISO_NFS")]
            device = xenrt.TEC().lookup("EXPORT_ISO_NFS_STATIC", None)
            if device:
                devices.append(device)

            for device in devices:
                # If we have a build with
                if self.execdom0("test -e /opt/xensource/bin/xe-mount-iso-sr",
                                 retval="code") == 0:
                    xenrt.TEC().logverbose("Using xe-mount-iso-sr to mount ISOs")
                    self.createISOSR(device)
                    continue

                # Skip if the mountpoint does not exist
                if self.execdom0("test -d /var/opt/xen/iso_import",
                                 retval="code") != 0:
                    xenrt.TEC().skip("Product does not use "
                                     "/var/opt/xen/iso_import")

                self.mountImports("iso", device, fstab=True)

                xenrt.sleep(60)

                # This method supports only one device
                break

        # Reset HA bits
        self.haLocalConfig = {}
        self.haStatefileBlocked = False
        self.haHeartbeatBlocks = {'allto': False,   'to': [],
                                  'allfrom': False, 'from': []}

        # Do any Orlando specific post install
        self.postInstall()
        
    def shutdown(self, sleeptime=120):
        """Perform a clean shutdown of the host"""
        # If we're HA enabled, need to remove myself from XenRT's
        # liveset
        if self.pool:
            if self.pool.haEnabled:
                uuid = self.getMyHostUUID()
                if uuid in self.pool.haLiveset:
                    self.pool.haLiveset.remove(uuid)
        cli = self.getCLIInstance()
        cli.execute("host-disable","uuid=%s" % (self.getMyHostUUID()))
        cli.execute("host-shutdown","uuid=%s" % (self.getMyHostUUID()))
        xenrt.sleep(sleeptime)    
        
    def getFreeMemory(self):
        """Return the number of MB of free memory the host claims to have."""
        # Try this way first:
        try:
            cli = self.getCLIInstance()
            mfk = cli.execute("host-data-source-query",
                              "host=%s data-source=memory_free_kib" %
                              (self.getMyHostUUID())).strip()
            if mfk == "nan":
                raise xenrt.XRTError(\
                    "host-data-source-query/memory_free_kib returned 'nan'")
            return int(float(mfk)/xenrt.KILO)
        except:
            # Fall back to the 4.1/4.0 version
            return int(self.getHostParam("memory-free"))/xenrt.MEGA
            
    def getDefaultInterface(self):
        """Return the enumeration ID for the configured default interface."""
        # First try a lookup based on the MAC address if known
        installnetwork = self.getInstallNetwork()
        if installnetwork:
            mac = self.getNICMACAddress(self.listSecondaryNICs(installnetwork)[0])
        else:
            mac = self.lookup("MAC_ADDRESS", None)
        if mac and not self.special.has_key('getDefaultInterface no PIF check'):
            try:
                ifs = self.minimalList("pif-list",
                                       "device",
                                       "MAC=%s physical=true" % (mac))
                if len(ifs) == 0:
                    raise xenrt.XRTFailure("Could not find any PID for %s" %
                                           (mac))
                return ifs[0]
            except Exception, e:
                xenrt.TEC().warning("Exception looking up default interface: "
                                    "%s" % (str(e)))
        # Otherwise fall back to the configuration
        return xenrt.GenericHost.getDefaultInterface(self)    

    def getBugToolRioHost(self, bugdir=None, extras=None):
        if not bugdir:
            bugdir = "%s/%s" % (xenrt.TEC().getLogdir(), self.getName())
        xenrt.command("mkdir -p %s" % (bugdir))
        retval = 0
        try:
            retval = self.execdom0("grep -q outfd /usr/sbin/xen-bugtool",
                         retval="code")
        except: # Try rebooting the host
            if not self.rebootingforbugtool:
                self.rebootingforbugtool = True
                xenrt.sleep(300) # Allow 5 minutes for all logs to sync
                
                # poke Xen to give us a crash-dump
                xenrt.TEC().warning("Poking Xen from job %s to give us a crashdump on %s" % (str(xenrt.GEC().jobid()), self.machine.name))
                try:
                    xenrt.command("/bin/echo -e \"\\x01\\x01\\x01C\\x05c.\" | console %s -f" % self.machine.name, timeout=120)
                except Exception, e:
                    xenrt.TEC().logverbose(str(e))
                xenrt.sleep(120)
                
                self.poweroff()
                xenrt.sleep(30)
                self.poweron()
                retval = self.execdom0("grep -q outfd /usr/sbin/xen-bugtool",
                             retval="code")
                self.rebootingforbugtool = False
            else:
                xenrt.sleep(1200) # Wait for host to come back up if another thread is getting the bugtool
                retval = self.execdom0("grep -q outfd /usr/sbin/xen-bugtool",
                             retval="code")
                

        if retval == 0:
            # Use stdout
            # Write it out with the same name as xen-bugtool itself
            # would generate so as not to break Jira bits etc. Also
            # use gmtime() so we use UTC
            bn = time.strftime("bug-report-%Y%m%d%H%M%S", time.gmtime())
            bbn = "%s_%s" % (self.getName(), bn)
            localbug = "%s/%s.tar.gz" % (bugdir, bn)
            self.execdom0("XEN_RT=yes XENRT_BUGTOOL_BASENAME=%s "
                          "/usr/sbin/xen-bugtool -s -y "
                          "--output=tar --outfd=1 | gzip -c" % (bbn),
                          nolog=True,
                          outfile=localbug)
        else:
            # Write to a file and copy
            bugtoolout = self.execdom0("XEN_RT=yes /usr/sbin/xen-bugtool -y")
            remotebug = re.search("(Writing tarball )(?P<br>.*)( successful.)",
                                  bugtoolout).group("br")   
            localbug = "%s/%s" % (bugdir, os.path.basename(remotebug))
            sftp = self.sftpClient()
            try:
                sftp.copyFrom(remotebug, localbug) 
            finally:
                sftp.close()
            self.execdom0("rm -f %s" % (remotebug))
        xenrt.TEC().logverbose("Saving bug tool report %s" % (localbug))
        return localbug


    def getBugTool(self, bugdir=None, extras=None, restrictTo=None):
        if not bugdir:
            bugdir = "%s/%s" % (xenrt.TEC().getLogdir(), self.getName())
        xenrt.command("mkdir -p %s" % (bugdir))

        cli = self.getCLIInstance()

        # Get the list of system capabilities. If this fails then we'll revert
        # to the legacy bugtool method
        try:
            data = cli.execute("host-get-system-status-capabilities",
                               "uuid=%s" % (self.getMyHostUUID()))
        except xenrt.XRTException, e:
            xenrt.TEC().warning(\
                "Exception from host-get-system-status-capabilities: %s" %
                (str(e)))
            return self.getBugToolRioHost(bugdir=bugdir, extras=extras)
        dom = xml.dom.minidom.parseString(data)
        cs = dom.getElementsByTagName("capability")
        caps = []
        capsno = []
        for c in cs:
            if str(c.getAttribute("default-checked")) == "yes":
                caps.append(str(c.getAttribute("key")))
            else:
                capsno.append(str(c.getAttribute("key")))

        # Any extra capablities asked for
        if extras:
            for extra in extras:
                if extra in caps:
                    # Already have it, nothing to do
                    pass
                elif extra in capsno:
                    caps.append(extra)
                else:
                    xenrt.TEC().warning(\
                        "Asked for extra bugtool capability '%s' which is "
                        "not available on host %s" % (extra, self.getName()))
        if restrictTo:
            is_known = set(restrictTo) - set(caps).union(set(capsno))
            if is_known:
                xenrt.TEC().warning(\
                    "Asked for bugtool capabilities '%s' "
                    "not available on host %s" % (list(is_known), self.getName()))
            caps = restrictTo

        # Stress tests can reduce the entries fetched
        if self.lookup("BUGTOOL_MODE_STRESS", False, boolean=True):
            excl = self.lookup("BUGTOOL_STRESS_EXCLUDES", "blobs")
            for ex in excl.split(","):
                if ex in caps:
                    caps.remove(ex)

        # Get the status report, initially to a temporary named file
        filename = "%s/xenrt%08x%08x.tar" % (bugdir,
                                             random.randint(0, 0x7fffffff),
                                             random.randint(0, 0x7fffffff))
        args = ["uuid=%s" % (self.getMyHostUUID()), "output=tar"]
        args.append("filename=%s" % (filename))
        args.append("entries=%s" % (string.join(caps, ",")))
        try:
            cli.execute("host-get-system-status", string.join(args))
        except xenrt.XRTException, e:        
            xenrt.TEC().warning(\
                "Exception from host-get-system-status: %s" % (str(e)))
            return self.getBugToolRioHost(bugdir=bugdir, extras=extras)
      
        # Find the bug-report directory name within the report and rename
        # the file to match
        t = tarfile.open(filename, "r")
        try:
            n = t.next()
            stem = n.name.split("/")[0]
        finally:
            t.close()
        localbugtar = "%s/%s.tar" % (bugdir, stem)
        os.rename(filename, localbugtar)
        localbug = localbugtar + ".gz"
        xenrt.command("nice gzip %s" % (localbugtar))

        xenrt.TEC().logverbose("Saving bug tool report %s" % (localbug))
        return localbug
        
    def checkEmergency(self):
        """See if this host is in emergency mode"""
        # This is a bit nasty, but if we're expecting to be off for HA, then
        # checking emergency mode will fail as the CLI won't respond
        if self.pool and self.pool.haEnabled and \
           (not self.getMyHostUUID() in self.pool.haLiveset):
            return False
        else:
            cli = self.getCLIInstance(local=True)
            emode = None
            try:
                emode = cli.execute("host-is-in-emergency-mode")
                if re.search("true", emode):
                    return True
                if re.search("false", emode):
                    return False
            except:
                # Use legacy method
                data = cli.execute("host-list", ignoreerrors=True)
                if not re.search("emergency", data):
                    if re.search("The host is still booting", data):
                        xenrt.TEC().warning("Using emergency mode check "
                                            "workaround")
                    else:
                        return False
                return True
            raise xenrt.XRTError("Unable to check emergency mode")

    def getExtraLogs(self, directory):

        cds = self.listCrashDumps()
        for cd in cds:
            cdr = "gcrashdump:%s" % (cd)
            if not cdr in self.thingsWeHaveReported:
                self.thingsWeHaveReported.append(cdr)
                xenrt.TEC().warning("Crash dump %s found" % (cd))
        cli = self.getCLIInstance()
        data = cli.execute("diagnostic-gc-stats")
        f = file("%s/diagnostic-gc-stats.txt" % (directory), "w")
        f.write(data)
        f.close()
        try:
            data = cli.execute("diagnostic-timing-stats")
            f = file("%s/diagnostic-timing-stats.txt" % (directory), "w")
            f.write(data)
            f.close()
        except:
            pass
        try:
            rss = int(self.execdom0("ps ax -o rss,cmd | "
                                    "grep /opt/xensource/bin/xap[i] | "
                                    "awk '{mem+=$1}END{print mem}'"))
            if rss > 60720:
                xenrt.TEC().warning("%s xapi RSS is %uMB" % (self.getName(),
                                                             rss/xenrt.KILO))
        except:
            pass
        # Get any 'alerts'
        try:
            data = cli.execute("message-list",nolog=True)
            f = file("%s/messages.txt" % (directory), "w")
            f.write(data)
            f.close()
        except:
            # Might be a build without alerts
            pass

    def enableDefaultADAuth(self):
        domain = xenrt.TEC().lookup(["AD_CONFIG", "DOMAIN"])
        (user, password) = xenrt.TEC().lookup(["AD_CONFIG", "USERS", "DOMAIN_JOIN"]).split(":", 1)

        # Join the domain

        cli = self.getCLIInstance()
        args = []
        args.append("auth-type=AD")
        args.append("service-name=\"%s\"" % domain)
        args.append("config:domain=\"%s\"" % domain)
        args.append("config:user=\"%s\"" % user)
        args.append("config:pass=\"%s\"" % password)
        cli.execute("pool-enable-external-auth", string.join(args))

    def getSCSIID(self, device):
        return self.execdom0("%s -g -s /block/%s" % (self.scsiIdPath(), device)).strip()

    def getFromMemInfo(self, field):
        meminfo = self.execdom0("cat /proc/meminfo")
        r = re.search(r"%s:\s+(\d+)\s+kB" % field, meminfo)
        if r:
            return int(r.group(1))
        return None

    def setXenCmdLine(self, set="xen", **kwargs):
        for key in kwargs:
            value = kwargs[key]
            self.execdom0('/opt/xensource/libexec/xen-cmdline --set-%s %s=%s' % (set, key, value))

    def _findXenBinary(self, binary):
        paths = ["/usr/lib64/xen/bin", "/usr/lib/xen/bin", "/opt/xensource/bin", "/usr/libexec/xen/bin"]
        for p in paths:
            joinedPath = os.path.join(p, binary)
            if self.execdom0('ls %s' % (joinedPath), retval="code") == 0:
                return joinedPath
        raise xenrt.XRTError("Couldn't find xen binary %s" % binary)
        
    def snmpdIsEnabled(self):
        return "3:on" in self.execdom0("/sbin/chkconfig --list snmpd")
        
    def disableSnmpd(self):
        self.execdom0("/sbin/chkconfig snmpd off")
    
    def enableSnmpd(self):
        self.execdom0("/sbin/chkconfig snmpd on")
        
    def scsiIdPath(self):
        return "/sbin/scsi_id"
        
    def iptablesSave(self):
        self.execdom0("service iptables save")

    def createNestedHost(self,
                         name=None,
                         cpus=2,
                         memory=4096,
                         diskSize=50,
                         sr=None,
                         networks=None):
        if not name:
            name = xenrt.randomGuestName()
        if not sr:
            sr="DEFAULT"
        name = "vhost-%s" % name
        g = self.createGenericEmptyGuest(memory=memory, vcpus=cpus, name=name)
        if not networks:
            networks = ["NPRI"]
        if networks[0] != "NPRI":
            raise xenrt.XRTError("First network must be NPRI")
        netDetails = []
        for i in range(len(networks)):
            mac = xenrt.randomMACXenSource()
            if i == 0:
                nicname = name
            else:
                nicname = "%s-nic%d" % (name, i)
            ip = xenrt.StaticIP4Addr(mac=mac, network=networks[i], name=name)
            g.createVIF(bridge=networks[i], mac=mac)
            netDetails.append((mac, ip))
        diskSize = diskSize * xenrt.GIGA
        g.createDisk(sizebytes=diskSize, sruuid=sr, bootable=True)
        g.paramSet("HVM-boot-params-order", "nc")
        if xenrt.TEC().lookup("NESTED_HVM", False, boolean=True):
            g.paramSet("platform:exp-nested-hvm", "1")
        
        (mac, ip) = netDetails[0]
        xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'MAC_ADDRESS'], mac)
        xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'PXE_MAC_ADDRESS'], mac)
        xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'HOST_ADDRESS'], ip.getAddr())
        xenrt.GEC().dbconnect.jobUpdate("VXS_%s" % ip.getAddr(), name)

        for i in range(1, len(netDetails)):
            (mac, ip) = netDetails[i]
            xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'NICS', 'NIC%d' % i, 'MAC_ADDRESS'], mac)
            xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'NICS', 'NIC%d' % i, 'IP_ADDRESS'], ip.getAddr())
            xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'NICS', 'NIC%d' % i, 'NETWORK'], networks[i])

        xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'CONTAINER_HOST'], self.getIP())
        xenrt.GEC().config.setVariable(['HOST_CONFIGS', name, 'PXE_CHAIN_LOCAL_BOOT'], "hd0")
        return name

    def applyFullLicense(self,v6server):
 
        license = XenServerLicenseFactory().maxLicenseSkuHost(self)
        LicenseManager().addLicensesToServer(v6server,license,getLicenseInUse=False)
        self.license(edition = license.getEdition(), v6server=v6server)
        
    def getIpTablesFirewall(self):
        """IPTablesFirewall object used to create and delete iptables rules."""
        return IpTablesFirewall(self)

    def isCentOS7Dom0(self):
        return False

    def writeUefiLocalBoot(self, nfsdir, pxe):
        raise xenrt.XRTError("UEFI is not supported on this version")

    def chooseSR(self, sr=None):
        """Choose an SR to use. Returns the SR UUID"""
        xenrt.TEC().logverbose("SR: %s" % sr)
        if not sr:
            if xenrt.TEC().lookup("OPTION_DEFAULT_SR", False, boolean=True):
                # Use the default SR defined by the pool/host
                return self.lookupDefaultSR()
            if self.defaultsr:
                srname = self.defaultsr
                sruuid = self.parseListForUUID("sr-list",
                                               "name-label",
                                               srname)
            else:
                sruuid = self.getLocalSR()
                xenrt.TEC().logverbose("Using local SR %s" % (sruuid))
        else:
            if xenrt.isUUID(sr):
                sruuid = sr
            elif sr == "DEFAULT":
                sruuid = self.lookupDefaultSR()
            elif sr == "Local storage":
                sruuid = self.getLocalSR()
            else:
                xenrt.TEC().logverbose("given sr is not UUID")
                sruuid = self.parseListForUUID("sr-list", "name-label", sr)
        
            
        return sruuid

    def isHAPEnabled(self):
        dmesg = self.execdom0("grep 'Hardware Assisted Paging' /var/log/xen/hypervisor.log || true")
       
        #for backward compatibility checking in /var/log/xen-dmesg
        if "Hardware Assisted Paging" not in dmesg:
            dmesg = self.execdom0("grep 'Hardware Assisted Paging' /var/log/xen-dmesg || true")

        return "HVM: Hardware Assisted Paging detected and enabled." in dmesg or\
                          "HVM: Hardware Assisted Paging (HAP) detected" in dmesg

    def resolveDistroName(self, distro):
        origDistro = distro
        special = {}

        m = re.match("^(oel[dw]?|sl[dw]?|rhel[dw]?|centos[dw]?)(\d)x$", distro)
        if m:
            # Fall back to RHEL if we don't have derivatives defined
            distro = self.lookup("LATEST_%s%s" % (m.group(1), m.group(2)),
                        self.lookup("LATEST_rhel%s" % m.group(2)).replace("rhel", m.group(1)))
        m = re.match("^(oel[dw]?|sl[dw]?|rhel[dw]?|centos[dw]?)(\d)u$", distro)
        if m:
            # Fall back to RHEL if we don't have derivatives defined
            distro = self.lookup("LATEST_%s%s" % (m.group(1), m.group(2)),
                        self.lookup("LATEST_rhel%s" % m.group(2)).replace("rhel", m.group(1)))
            if m.group(1) == "centos":
                special['UpdateTo'] = "latest"
            else:
                updateMap = xenrt.TEC().lookup("LINUX_UPDATE")
                match = ""
                newdistro = xenrt.getUpdateDistro(distro)
                if newdistro != distro:
                    special['UpdateTo'] = newdistro
                else:
                    special['UpdateTo'] = None
        
        m = re.match("^(oel[dw]?|sl[dw]?|rhel[dw]?|centos[dw]?)(\d+)xs$", distro)
        if m:
            distro = "%s%s" % (m.group(1), m.group(2))
            special['XSKernel'] = True
        xenrt.TEC().logverbose("Resolved %s to %s with %s (host is %s)" % (origDistro, distro, special, self.productVersion))
        return (distro, special)

    def getDeploymentRecord(self):
        ret = super(Host, self).getDeploymentRecord()
        ret['srs'] = []
        for s in [x for x in self.parameterList("sr-list", params=["type", "uuid", "name-label"]) if x['type'] not in ("iso", "udev")]:
            ret['srs'].append({
                "type": s['type'],
                "uuid": s['uuid'],
                "name": s['name-label']})
        return ret

    def modifyRawStorageCommand(self, sr, command):
        """
        Evaluate SR and modify command if required.

        @param command: command to run from dom0.
        @param sr: a storage repository object or sruuid.
        @return: a modified command
        """

        return command

    def execRawStorageCommand(self,
                            sr,
                            command,
                            username=None,
                            retval="string",
                            level=xenrt.RC_FAIL,
                            timeout=300,
                            idempotent=False,
                            newlineok=False,
                            nolog=False,
                            outfile=None,
                            useThread=False,
                            getreply=True,
                            password=None):

        """
        Raw storage commands such as lvcreate, pvresize and etc may need to be
        modified before executed.
        """

        # Thin provisioning SR requires to run raw storage command via xenvm
        # as storages, which is created via xenvmd, are only exposed by
        # xenvmd.
        command = self.modifyRawStorageCommand(sr, command)

        return self.execdom0(command,
                            username,
                            retval,
                            level,
                            timeout,
                            idempotent,
                            newlineok,
                            nolog,
                            outfile,
                            useThread,
                            getreply,
                            password
                            )
    
    def getDom0Partitions(self):

        """
        Return dom0 disk partitions and there size in KB
        return Format: {1: 19327352832, 2: 19327352832, 3: '*', 4: 535822336, 5: 4294967296, 6: 1072693248} 
        """
        primarydisk = self.getInventoryItem("PRIMARY_DISK")
        partitions = [p.split(' ') for p in self.execdom0("sgdisk -p %s | awk '$1 ~ /[0-9]+/ {print $1,$4,$5}'" % primarydisk).splitlines()]
        return dict([(int(p[0]), float(p[1]) * (xenrt.GIGA if p[2]=='GiB' else xenrt.MEGA)) for p in partitions])

    def compareDom0Partitions(self, partitions):

        """
        Return True if dom0 disk partition schema matches the schema 'partition' else return False
        """
        dom0Partitions = self.getDom0Partitions()
        
        if len(partitions) != len(dom0Partitions):
            missingPartitions = list(set(partitions.keys())-set(dom0Partitions.keys()))
            if len(missingPartitions) > 1 or xenrt.TEC().lookup('SR_ON_PRIMARY_DISK', True, boolean=True):
                log("Number of Partitions in dom0 is different from expected number of partitions. Expected %s. Found %s" % (partitions,dom0Partitions ))
                return False
            partitions.pop(missingPartitions[0], None)
            
        diffkeys = [k for k in partitions if partitions[k] != "*" and int(partitions[k]) != int(dom0Partitions[k])]
        if diffkeys:
            log("One or more partition size is different from expected. Expected %s. Found %s" % ((partitions,dom0Partitions )))
            return False
        log("Dom0 has expected partition schema: %s" % dom0Partitions)
        return True

    def checkSafe2Upgrade(self):
        """Function to check if new partitions will be created on upgrade to dundee- CAR-1866"""

        step("Call testSafe2Upgrade function and check if its output is as expected")
        sruuid = []
        sruuid.extend(self.getSRs(type="ext", local=True))
        sruuid.extend(self.getSRs(type="lvm", local=True))
        expectedOutput = "true"
        for sr in sruuid:
            pbd = self.minimalList("pbd-list",args="sr-uuid=%s" % (sr))[0]
            localSrOnSda = self.getInventoryItem("PRIMARY_DISK") in self.genParamGet("pbd",pbd,"device-config", "device")
            if localSrOnSda:
                vdis = len(self.minimalList("vdi-list", args="sr-uuid=%s" % (sr)))
                log("Number of VDIs on local stotage: %d" % vdis)
                srsize = int(self.execdom0("blockdev --getsize64 %s" % self.getInventoryItem("PRIMARY_DISK")))/xenrt.GIGA
                log("Size of disk: %dGiB" % srsize)
                if srsize < 46:
                    # Minimum supported primary disk size for new partitions is 46GB
                    expectedOutput = "not_enough_space"
                elif (isinstance(self, xenrt.lib.xenserver.DundeeHost) and self.compareDom0Partitions(self.lookup("DOM0_PARTITIONS_OLD"))) or vdis > 0:
                    expectedOutput = "false"
                else:
                    expectedOutput = "true"
                break
        log("Plugin should return: %s" % expectedOutput)

        cli = self.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (self.getMyHostUUID()))
        args.append("plugin=prepare_host_upgrade.py")
        args.append("fn=testSafe2Upgrade")
        output = cli.execute("host-call-plugin", string.join(args), timeout=300).strip()
        if output != expectedOutput:
            raise xenrt.XRTFailure("Unexpected output: %s" % (output))
        xenrt.TEC().logverbose("Expected output: %s" % (output))

        step("Call main plugin and check if testSafe2Upgrade returned true")
        args = []
        args.append("host-uuid=%s" % (self.getMyHostUUID()))
        args.append("plugin=prepare_host_upgrade.py")
        args.append("fn=main")
        args.append("args:url=%s/xe-phase-1/" % (xenrt.TEC().lookup("FORCE_HTTP_FETCH") + xenrt.TEC().lookup("INPUTDIR")))
        output = cli.execute("host-call-plugin", string.join(args), timeout=900).strip()
        if output != "true":
            raise xenrt.XRTFailure("Unexpected output: %s" % (output))
        xenrt.TEC().logverbose("Expected output: %s" % (output))

        if expectedOutput=="true":
            step("Check if safe2upgrade file is created")
            res = self.execdom0('ls /var/preserve/safe2upgrade')
            if 'No such file or directory' in res or res.strip() == '':
                raise xenrt.XRTFailure("Unexpected output: /var/preserve/safe2upgrade file is not created")
            log("/var/preserve/safe2upgrade file is created as expected")
        return True if expectedOutput == "true" else False

    def isHostLicensed(self):

        factory = XenServerLicenseFactory()
        noLicense = factory.noLicense()
        return (not (self.paramGet("edition") == noLicense.getEdition()))

#############################################################################

class MNRHost(Host):
    """Represents a MNR+ host"""

    def __init__(self, machine, productVersion="MNR",productType="xenserver"):
        Host.__init__(self, machine, productVersion=productVersion,productType=productType)
        self.special["dom0 uses hvc"] = True
        self.controller = None

    def getTestHotfix(self, hotfixNumber):
        workdir = xenrt.TEC().getWorkdir()
        if xenrt.command("test -e %s/patchapply" % workdir, retval="code") != 0:
            xenrt.getTestTarball("patchapply", extract=True, directory=workdir)
        
        ver = self.productRevision.split("-")[0]
        if os.path.exists("%s/patchapply/hotfix-%s-test%u.xsupdate" % (workdir, ver, hotfixNumber)):
            return "%s/patchapply/hotfix-%s-test%u.xsupdate" % (workdir, ver, hotfixNumber)
        return "%s/patchapply/hotfix-mnr56-test%u.xsupdate" % (workdir, hotfixNumber)

    def __detect_vswitch(self):
        if self.execdom0("cat /etc/xensource/network.conf").strip() == "openvswitch":
            self.special['Network subsystem type'] = "vswitch"
        else:
            self.special['Network subsystem type'] = "linux"

        xenrt.TEC().logverbose("Network subsystem type: %s" % self.special['Network subsystem type'])

    def enablevswitch(self, reboot=True):
        if self.special['Network subsystem type'] == "linux":
            self.execdom0("xe-switch-network-backend openvswitch")
            self.special['Network subsystem type'] = "vswitch"
            if reboot:
                self.reboot()

    def disablevswitch(self, reboot=True):
        if self.special['Network subsystem type'] == "vswitch":
            self.execdom0("xe-switch-network-backend  bridge")
            self.special['Network subsystem type'] = "linux"
            if reboot:
                self.reboot()

    def associateDVS(self, controller):
        if self.special['Network subsystem type'] == "vswitch":
            xenrt.TEC().logverbose("Associating host %s with controller." % (self.getName()))
            self.controller = controller
            self.controller.addHostToController(self)
            if xenrt.TEC().lookup("WORKAROUND_NIC_RESTART", False, boolean=True):
                if self.controller:
                    self.controller.place.reboot()

    def disassociateDVS(self):
        if self.special['Network subsystem type'] == "vswitch":
            xenrt.TEC().logverbose("Disassociating host %s from controller." % (self.getName()))
            self.controller.removeHostFromController(self)
            if xenrt.TEC().lookup("WORKAROUND_NIC_RESTART", False, boolean=True):
                if self.controller:
                    self.controller.place.reboot()
            self.controller = None

    def __detect_v6(self):
        """Detect whether the host requires v6 licensing"""
        try:
            self.paramGet("software-version", "dbv")
            # If this succeeds then a dbv field is present, so we are on v6
            xenrt.TEC().logverbose("V6 licensing is required")
            self.special['v6licensing'] = True
            # See if we are using early release licensing
            try:
                details = self.getLicenseDetails()                
                if details["earlyrelease"] == "true":
                    self.special['v6earlyrelease'] = True
                else:
                    self.special['v6earlyrelease'] = False
            except:
                self.special['v6earlyrelease'] = False
        except Exception, e:
            xenrt.TEC().logverbose("Error getting DBV: V6 licensing is not required")
            xenrt.TEC().logverbose(str(e))
            if re.search(r'Unable to contact server\. Please check server and port settings\.', str(e)):
                raise e
            # No dbv field, so we're not using v6
            self.special['v6licensing'] = False

    def existing(self, doguests=True, guestsInRegistry=True):
        Host.existing(self,doguests, guestsInRegistry)
        self.__detect_vswitch()
        self.__detect_v6()

    def installComplete(self, handle, waitfor=False, upgrade=False):
        Host.installComplete(self, handle, waitfor, upgrade)

        self.__detect_vswitch()
        self.__detect_v6()
        if xenrt.TEC().lookup("OPTION_ENABLE_CC", False, boolean=True) and \
           not self.isCCEnabled():
            xenrt.TEC().logverbose("Enabling CC restrictions due to OPTION_ENABLE_CC")
            self.enableCC()

    def populateSubclass(self, x):
        Host.populateSubclass(self, x)
        x.controller = self.controller

    def guestFactory(self):
        return xenrt.lib.xenserver.guest.MNRGuest

    def removeNetwork(self, bridge=None, nwuuid=None):
        if bridge:
            xenrt.TEC().logverbose("Removing %s" % bridge)
        if not nwuuid:
            nwuuid = self.getNetworkUUID(bridge)
        cli = self.getCLIInstance() 
        cli.execute("network-destroy", "uuid=%s" % (nwuuid))

    def removeVLAN(self, vlan):
        """Remove a VLAN"""

        if self.special['Network subsystem type'] == "linux":
            return Host.removeVLAN(self, vlan)
    
        # create vlan creates a new untagged pif, but that is 
        # cleaned up when the vlan is destroyed via the vlan uuid
        vlanuuid = self.parseListForUUID("pif-list", "VLAN", vlan,
                                         args="host-uuid=%s" %
                                              (self.getMyHostUUID())) 
        networkuuid = self.genParamGet("pif", vlanuuid, "network-uuid")
        bridge = self.genParamGet("network", networkuuid, "bridge")
        nic = self.genParamGet("pif", vlanuuid, "device")
        vlanif = "%s.%u" % (nic, vlan)
        
        cli = self.getCLIInstance()
        cli.execute("vlan-destroy", "uuid=%s" % (vlanuuid))
        
        try:
            vlanuuid = self.parseListForUUID("pif-list", "VLAN", vlan)
            raise xenrt.XRTFailure("VLAN %d exists." % (vlan))
        except:
            pass

        try:
            self.execdom0("ifconfig %s" % bridge)
            raise xenrt.XRTFailure("VLAN fake-bridge interface %s exists on the host." % bridge)
        except:
            pass

    def checkVLAN(self, vlan, nic="eth0"):
        """Check VLAN has been installed correctly."""
        
        if self.special['Network subsystem type'] == "linux":
            return Host.checkVLAN(self, vlan, nic)

        hostuuid = self.getMyHostUUID()
        vlanuuid = self.parseListForUUID("pif-list", "VLAN", vlan,
                                         args="host-uuid=%s" % hostuuid)

        networkuuid = self.genParamGet("pif", vlanuuid, "network-uuid")
        bridge = self.genParamGet("network", networkuuid, "bridge")
        device = self.genParamGet("pif", vlanuuid, "device")

        parent_pifuuid = self.parseListForUUID("pif-list", "device", nic,
                                               args="host-uuid=%s VLAN=-1" % 
                                               (hostuuid))
        
        parent_netuuid = self.genParamGet("pif", parent_pifuuid, 'network-uuid')
        parent_br = self.genParamGet("network", parent_netuuid, "bridge")
        
        if device != nic:
            raise xenrt.XRTFailure("NIC mismatch %s != %s." % (device, nic))

        try:
            self.execdom0("ifconfig %s" % bridge)
        except:
            raise xenrt.XRTFailure("VLAN fake-bridge interface %s does not exist." % bridge)

        try:
            actual_vlan = int(self.execdom0("ovs-vsctl br-to-vlan %s" % bridge).strip())
            if vlan != actual_vlan:
                raise xenrt.XRTFailure("VLAN mismatch %u != %u." % (actual_vlan, vlan))
        except:
            raise xenrt.XRTFailure("Unable to determine VLAN for fake-bridge interface %s." % bridge)

        try:
            actual_parent = self.execdom0("ovs-vsctl br-to-parent %s" % bridge).strip()
            if parent_br != actual_parent:
                raise xenrt.XRTFailure("Bridge parent mismatch %s != %s." % (parent_br, actual_parent))
        except:
            raise xenrt.XRTFailure("Unable to determine parent of fake-bridge interface %s." % bridge)

    def license(self, sku="XE Enterprise", edition=None, expirein=None, v6server=None, activateFree=True, applyEdition=True):
        if self.special.has_key('v6licensing') and self.special['v6licensing']:
            # Use v6 licensing

            if not edition:
                # Map old stlye skus to new style editions
                editions = {'XE Enterprise': 'enterprise',
                            'XE Server': 'enterprise',
                            'XE Express': 'free',
                            'FG Free': 'free',
                            'FG Paid': 'enterprise',
                            'free': 'free',
                            'advanced': 'advanced',
                            'enterprise': 'enterprise',
                            'platinum': 'platinum'}
                if not editions.has_key(sku):
                    raise xenrt.XRTError("No edition mapping for sku %s" % (sku))
                edition = editions[sku]                    

            if expirein and not edition == "free":
                # Enable the license expiry FIST point
                expiretime = xenrt.util.timenow() + (3600*24*expirein)
                # Convert this to a Xapi timestamp
                xapitime = xenrt.util.makeXapiTime(expiretime)
                # Write it in to the FIST file
                self.execdom0("echo '%s' > /tmp/fist_set_expiry_date" % (xapitime))
                # Restart xapi
                self.restartToolstack()
                self.waitForEnabled(300)
            else:
                # Remove the FIST point if it exists
                rc = self.execdom0("[ -e /tmp/fist_set_expiry_date ]",retval="code")
                if rc == 0:
                    self.execdom0("rm -f /tmp/fist_set_expiry_date")
                    self.restartToolstack()
                    self.waitForEnabled(300)

            # Now apply the license
            cli = self.getCLIInstance()
            args = []
            args.append("host-uuid=%s" % (self.getMyHostUUID()))
            args.append("edition=%s" % (edition))
            if v6server:
                args.append("license-server-address=%s" % (v6server.getAddress()))
                args.append("license-server-port=%s" % (v6server.getPort()))
            else:
                if self.special.has_key('v6earlyrelease') and self.special['v6earlyrelease']:
                    (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_PREVIEW_LICENSE_SERVER").split(":")
                else:
                    (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_LICENSE_SERVER").split(":")

                args.append("license-server-address=%s" % (addr))
                args.append("license-server-port=%s" % (port))
            if applyEdition:
                cli.execute("host-apply-edition", string.join(args))

            if edition == "free" and activateFree:
                # Apply a traditional free license, which will 'activate' the host
                return Host.license(self, sku="FG Free", expirein=expirein)

            # If we used a real v6 server, check its details were stored correctly
            if v6server:
                addr = self.paramGet("license-server", "address")
                port = int(self.paramGet("license-server", "port"))
                if addr != v6server.getAddress() or port != v6server.getPort():
                    raise xenrt.XRTFailure("License server address and port not"
                                           " correctly reported",
                                           data="Expecting %s:%s, found %s:%s" %
                                                (v6server.getAddress(),
                                                 v6server.getPort(),
                                                 addr, port))

            # Check it was applied correctly
            details = self.getLicenseDetails()
            if details['edition'] != edition:
                raise xenrt.XRTFailure("Reported edition %s does not match "
                                       "applied edition %s" %
                                       (details['edition'], edition))
            # Check the legacy info
            if edition == "free":
                expectedSKU = "XE Express"
            elif (edition == "enterprise" or edition == "platinum"
                  or edition == "enterprise-xd"):
                expectedSKU = "XE Enterprise"
            elif edition == "advanced":
                expectedSKU = "advanced"
            else:
                raise xenrt.XRTError("Unknown edition %s" % (edition))
            if not details.has_key("sku_type"):
                raise xenrt.XRTError("Unable to find legacy license SKU")            
            if details['sku_type'] != expectedSKU and details['sku_type'] != edition:
                raise xenrt.XRTFailure("Legacy license SKU '%s' is not what we "
                                       "expected ('%s' or '%s')" %
                                       (details['sku_type'], expectedSKU, edition))
            
        else:
            Host.license(self, sku=sku, expirein=expirein)

    def getLicenseDetails(self):
        ld = Host.getLicenseDetails(self)
        if self.special.has_key('v6licensing') and self.special['v6licensing']:
            ld['edition'] = self.paramGet("edition")
        return ld

    def getEdition(self):
        return self.paramGet("edition")

    def vswitchAppCtl(self, cmd):
        pid = self.execdom0("/bin/cat /var/run/openvswitch/ovs-vswitchd.pid").strip()
        return self.execdom0("/usr/bin/ovs-appctl -t /var/run/openvswitch/ovs-vswitchd.%s.ctl -e %s"
                             % (pid, cmd))
    
    def showPortMappings(self, bridge):
        return self.vswitchAppCtl("fdb/show %s" % (bridge))
    
    def calculateBondingHash(self, mac, vlan=None):
        if self.special['Network subsystem type'] == "linux":
            return Host.calculateBondingHash(self, mac)
        if vlan is None:
            nwuuid = self.parseListForOtherParam("vif-list", "MAC", mac, "network-uuid")
            if not nwuuid:
                nwuuid = self.parseListForOtherParam("pif-list", "MAC", mac, "network-uuid")
            vlan = int(self.parseListForOtherParam("pif-list", "network-uuid", nwuuid, "VLAN"))
        if vlan > 0:
            return int(self.vswitchAppCtl("bond/hash %s %s" % (mac, vlan)).strip())
        else:
            return int(self.vswitchAppCtl("bond/hash %s" % mac).strip())

    def setvSwitchLogLevel(self, level):
        self.vswitchAppCtl("vlog/set %s" % (level))

    def getvSwitchLogLevel(self):
        return self.vswitchAppCtl("vlog/list").strip()

    def vSwitchCoverageLog(self):
        self.vswitchAppCtl("coverage/log")
        
    def predictVMMemoryOverhead(self, memoryMB, isHVM):
        """Predict the memory overhead (due to shadow etc.) for a VM
        of the specified size and type (HVM/PV). Returns overhead in MB."""
        # Assume HVM VMs always need shadow memory (even HAP systems will need shadow for migrate etc.
        includeShadow = isHVM
        # Cowley and later preallocate shadow for PV as well to ensure
        # migration can complete without running out of memory. (see CA-47369)
        if not isHVM and isinstance(self, xenrt.lib.xenserver.MNRHost) and not self.productVersion == 'MNR':
            includeShadow = True
        if includeShadow:
            return int(memoryMB/128) + 1
        return 0

    def maximumMemoryForVM(self, guest):
        """Return the maximum memory size for a new VM taking into account
        available memory and computed VM overhead."""

        if not isinstance(self, xenrt.lib.xenserver.MNRHost):
            return Host.maximumMemoryForVM(self, guest)

        hosttotalmem = xenrt.roundDownMiB(int(self.paramGet("memory-total")))
        hostoverhead = xenrt.roundUpMiB(int(self.paramGet("memory-overhead")))
        dom0actual = xenrt.roundUpMiB(int(self.genParamGet("vm",
                                               self.getMyDomain0UUID(),
                                               "memory-actual")))
        dom0overhead = xenrt.roundUpMiB(int(self.genParamGet("vm",
                                                 self.getMyDomain0UUID(),
                                                 "memory-overhead")))
        totalmem = hosttotalmem - hostoverhead - dom0actual - dom0overhead
        xenrt.TEC().logverbose("Available host memory for %s is %u bytes" %
                               (self.getName(), totalmem))
        xenrt.TEC().logverbose(\
            "total=%u hostoverhead=%u dom0=%u dom0overhead=%u" %
            (hosttotalmem, hostoverhead, dom0actual, dom0overhead))
        if dom0actual == 0:
            raise xenrt.XRTError("Dom0 memory-actual reports 0 bytes",
                                 self.getName())

        # Work out the overhead of our new VM
        cli = self.getCLIInstance()
        overhead = int(cli.execute("vm-compute-memory-overhead",
                                   "uuid=%s" % (guest.getUUID()), strip=True))

        # Calculate the current shadow memory.
        # Exclude the extra for the vCPUs as that memory usage won't change when we increase the allocation
        currentStaticMax = int(guest.paramGet("memory-static-max"))
        currentShadowMem = currentStaticMax / 128
        # Subtract the current shadow memory from the VM overhead
        overhead = overhead - currentShadowMem
        overhead = xenrt.roundUpMiB(overhead)

        mem = totalmem - overhead

        # Now we've got the total free memory available for the VM, of which some (vm_static_max/128) will be used for shadow memory
        # Work out how much we can use for VM memory

        mem = mem * 127/128

        # Now convert to megabytes
        
        mem = xenrt.roundDownMiB(mem) / xenrt.MEGA
        xenrt.TEC().logverbose("Guest %s computed overhead %u bytes" %
                               (guest.getName(), overhead))
        xenrt.TEC().logverbose("Calculated maximum memory %uMB" % (mem))
        return mem

    def getBondInfo(self,bond):
        """Gets information about a network bond"""

        if self.special['Network subsystem type'] == "linux":
            return Host.getBondInfo(self,bond)

        lines = self.vswitchAppCtl("bond/show %s" % bond).split("\n")
        xenrt.TEC().logverbose("bond/show = %s" % lines)

        info = {}
        slaves = {}
        
        info['slb'] = {}
        info['mode'] = None # bond modes are not supported on all versions of vSwitch
        info['load'] = {}
        slave = None
        for line in lines:
            if line.startswith("updelay: ") or \
               line.startswith("downdelay:" ) or \
               line.startswith("next rebalance: "):
                # uninteresting fields
                pass
            elif line.startswith("slave "):
                statusmap = {'enabled': 'up', 'disabled': 'down'}
                _,slave,status = line.split()
                slave = slave.rstrip(":")
                info['load'][slave] = 0

                assert(not slaves.has_key(slave))
                slaves[slave] = {}
                uuid = self.parseListForUUID("pif-list VLAN=-1 host-uuid=%s" %
                                             (self.getMyHostUUID()),
                                             "device", slave)
                MAC = self.genParamGet("pif", uuid, "MAC")
                slaves[slave]['status'] = statusmap[status]
                slaves[slave]['hwaddr'] = MAC
            elif line.startswith("bond_mode: "):
                info['mode'] = line.split(":")[1].strip()
            elif line.startswith("\tactive slave"):
                assert(slave)
                info['active_slave'] = slave
            elif line.startswith("\tupdelay expires"):
                assert(slave)
                slaves[slave]['status'] = "down"
            elif line.startswith("\tdowndelay expires"):
                assert(slave)
                slaves[slave]['status'] = "up"
            elif line[:6] == "\thash ":
                assert(slave)
                _,hash,_ = line.split(None, 2)
                hash = hash.rstrip(":")
                info['slb'][int(hash)] = slave                               
                load = re.search(":\s(.*)\skB",line)
                load = int(load.group(1))
                info['load'][slave]=info['load'][slave] + load                
            elif line[:2] == "\t\t":
                assert(re.match("[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}$", line[2:]))
            
        info['slaves'] = slaves.keys()
        
        return (info,slaves)

    def getNetDevInfo(self, dev):
        info = {}
        lines = self.execdom0("cat /proc/net/dev").split("\n")

        for line in lines:
            m = re.search("^ *([\w\.]*): *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *(\d+) *", line)
            if m != None and m.group(1) == dev:
                info["rx_bytes"] = m.group(2)
                info["rx_packets"] = m.group(3)
                info["rx_errs"] = m.group(4)
                info["rx_drop"] = m.group(5)
                info["rx_fifo"] = m.group(6)
                info["rx_frame"] = m.group(7)
                info["rx_compressed"] = m.group(8)
                info["rx_multicast"] = m.group(9)
                info["tx_bytes"] = m.group(10)
                info["tx_packets"] = m.group(11)
                info["tx_errs"] = m.group(12)
                info["tx_drop"] = m.group(13)
                info["tx_fifo"] = m.group(14)
                info["tx_colls"] = m.group(15)
                info["tx_carrier"] = m.group(16)
                info["tx_compressed"] = m.group(17)
                break

        return info

    def checkNetworkInterfaceConfigLinuxBridgeFiles(self, name, proto, ip, netmask, gateway):
        return Host.checkNetworkInterfaceConfig(self, name, proto, ip, netmask, gateway)

    def checkNetworkInterfaceConfig(self, name, proto, ip, netmask, gateway):
        if self.special['Network subsystem type'] == "linux":
            return self.checkNetworkInterfaceConfigLinuxBridgeFiles(name, proto, ip, netmask, gateway)
        else:
            return self.checkNetworkInterfaceConfigRuntime(name, proto, ip, netmask, gateway)
    
    def checkNetworkInterfaceConfigRuntime(self, name, proto, ip, netmask, gateway):

        name = str(name)
        if re.search("^\d$", name):
            name = self.LINUX_INTERFACE_PREFIX + name
        name = name.replace("eth", self.LINUX_INTERFACE_PREFIX)
            
        ok = 1
        
        if proto == "dhcp":
            if self.execdom0("test -e /var/run/dhclient-%s.pid" % name, retval="code") != 0:
                xenrt.TEC().reason("No dhclient PID file found for interface %s " % name)
                ok = 0
            else:
                pid = int(self.execdom0("cat /var/run/dhclient-%s.pid" % name).strip())
                if self.execdom0("test -d /proc/%d" % pid, retval="code") != 0:
                    xenrt.TEC().reason("No process found with PID %d" % pid)
                    ok = 0
                elif os.path.basename(self.execdom0("readlink /proc/%d/exe" % pid).strip()) != "dhclient":
                    xenrt.TEC().reason("Process %d is not /sbin/dhclient" % pid)
                    ok = 0
        elif proto == "static":
            if self.execdom0("test -e /var/run/dhclient-%s.pid" % name, retval="code") == 0:
                pid = int(self.execdom0("cat /var/run/dhclient-%s.pid" % name).strip())
                if self.execdom0("test -d /proc/%d" % pid, retval="code") == 0 and \
                   os.path.basename(self.execdom0("readlink /proc/%d/exe" % pid).strip()) == "dhclient":
                    ok = 0
                    xenrt.TEC().reason("dhclient (%d) found for static interface" % pid)

            m=None
            ipcfg = [x.strip() for x in self.execdom0('ifconfig %s' % name).split("\n") if re.match("^inet ", x.strip())]
            if len(ipcfg) == 0:
                xenrt.TEC().reason("No IP address configured on device %s" % name)
            elif len(ipcfg) > 1:
                xenrt.TEC().reason("Multiple IP addresses configured on device %s" % name)
            else:
                m = re.match("inet (addr:)?([0-9\.]+).+?(netmask |Mask:)([0-9\.]+)", ipcfg[0])

            if not m:
                xenrt.TEC().reason("Cannot determine interface configuration for %s" % name)
                ok = 0
            else:
                if m.group(2) != ip:
                    ok = 0
                    xenrt.TEC().reason("Configuration of %s has "
                                       "IP address %s (expected %s)" %
                                       (name, m.group(2), ip))
                if m.group(4) != netmask:
                    ok = 0
                    xenrt.TEC().reason("Configuration of %s has "
                                       "NETMASK %s (expected %s)" %
                                       (name, m.group(4), netmask))

            # There is no way to confirm the gateway configured for a
            # given device unless it is actually being usedas the
            # default route. The default route is via the single
            # device with PIF.other-config:default=true or the
            # management interface if no other PIF is configured.            
            #
            # IFF the default route is configured for this device then
            # we can confirm that it is being used as the default route
            dest,gw,genmask,_,_,_,_,dev = self.execdom0("route -n | grep ^0.0.0.0").split()
            assert(dest == "0.0.0.0" and genmask == "0.0.0.0")
            if dev == name and gateway != gw:
                ok = 0
                xenrt.TEC().reason("Default route to device %s is "
                                   "via %s (expected %s)" %
                                   (name, gw, gateway))
        elif proto == "none":
            pass
        
        return ok

    def resetToFreshInstall(self, setupISOs=False):

        # Reset CC-Xen option
        self.execdom0("sed -i 's/ cc-restrictions//g' /boot/extlinux.conf || true")

        # Reset CC-SSL setting
        self.execdom0("rm -f /var/xapi/verify_certificates")
        # Brute force delete any certs since we're not sure whether the host is
        # in a (healthy) pool, pool-certificate-uninstall could cause trouble
        self.execdom0("rm -f /etc/stunnel/certs/*")
        
        # Continute the default resetToFreshInstall method
        Host.resetToFreshInstall(self, setupISOs=setupISOs)
    

    ########################################################################
    # RBAC methods
    def allow(self, subject, role=None, useapi=False):
        """Allow this subject access to this pool optionally assigning a
        role."""
        Host.allow(self, subject, role=role, useapi=useapi)
        if role:
            try:
                self.addRole(subject, role)
                if self.pool:
                    # Allow time for the change to propogate through the pool
                    xenrt.sleep(60)
            except Exception, e:
                # Probably a non-RBAC build
                xenrt.TEC().warning("Exception trying to add a role when "
                                    "adding a subject: %s" % (str(e)))

    def addRole(self, subject, role):
        xenrt.TEC().logverbose("Adding role %s to subject %s." % (role, subject))
        uuid = self.getSubjectUUID(subject)
        if not uuid:
            raise xenrt.XRTError("Subject %s not found." % (subject))
        cli = self.getCLIInstance()
        args = []
        args.append("role-name=%s" % (role))
        args.append("uuid=%s" % (uuid))
        cli.execute("subject-role-add", string.join(args))
        subject.roles.add(role)

    def removeRole(self, subject, role):
        xenrt.TEC().logverbose("Removing role %s from subject %s." % (role, subject))
        uuid = self.getSubjectUUID(subject)
        if not uuid:
            raise xenrt.XRTError("Subject %s not found." % (subject))
        cli = self.getCLIInstance()
        args = []
        args.append("role-name=%s" % (role))
        args.append("uuid=%s" % (uuid))
        cli.execute("subject-role-remove", string.join(args))
        subject.roles.remove(role)

    ########################################################################
    # CC methods

    def isCCEnabled(self):
        """Are Common Criteria restrictions enabled?"""
        cc = self.execdom0("grep cc-restrictions /boot/extlinux.conf",
                           retval="code", level=xenrt.RC_OK) == 0
        xenrt.TEC().logverbose("CC restrictions are currently %s." % (cc and "ON" or "OFF"))
        return cc

    def enableCC(self, reboot=True):
        """Enable the Common Criteria restrictions."""
        xenrt.TEC().logverbose("Enabling the Common Criteria restrictions.")
        self.execdom0("sed -i 's/xen[^\s]*\.gz/& cc-restrictions/g' /boot/extlinux.conf")
        self.execdom0("sync")
        if reboot:
            self.reboot()

    def disableCC(self, reboot=True):
        """Disable the Common Criteria restrictions."""        
        xenrt.TEC().logverbose("Disabling the Common Criteria restrictions.")
        self.execdom0("sed -i 's/ cc-restrictions//g' /boot/extlinux.conf")
        self.execdom0("sync")
        if reboot:
            self.reboot()

    def enableSSLVerification(self):
        """Enable SSL certificate verification"""
        self.execdom0("touch /var/xapi/verify_certificates")
        self.execdom0("service xapi stop")
        self.execdom0("pkill stunnel || true")
        self.execdom0("service xapi start")
        self.waitForXapi(600, desc="xapi startup after SSL verification change")


    def disableSSLVerification(self):
        """Disable SSL certificate verification"""
        self.execdom0("rm -f /var/xapi/verify_certificates")
        self.execdom0("service xapi stop")
        self.execdom0("pkill stunnel || true")
        self.execdom0("service xapi start")
        self.waitForXapi(600, desc="xapi startup after SSL verification change")

    def isSSLVerificationEnabled(self):
        """Determine the status of SSL certificate verification"""
        enabled = self.execdom0("ls /var/xapi/verify_certificates",
                                retval="code") == 0
        xenrt.TEC().logverbose("SSL verification is %s." % (enabled and "ON" or "OFF"))
        return enabled

    def installCertificate(self, cert):
        if self.isCertificateInstalled(cert):
            xenrt.TEC().logverbose("Certificate is already installed.")
            return
        # This is because we want to be able to choose the certificate by name
        # to uninstall it later...
        cwd = os.getcwd()
        path, name = os.path.split(cert)
        os.chdir(path)
        try:
            cli = self.getCLIInstance()
            cli.execute("pool-certificate-install", "filename=" + name)
        finally:
            os.chdir(cwd)

    def uninstallCertificate(self, cert):
        path, name = os.path.split(cert)
        if self.isCertificateInstalled(cert):
            cli = self.getCLIInstance()
            cli.execute("pool-certificate-uninstall", "name=" + os.path.basename(cert))

    def isCertificateInstalled(self, cert):
        name = os.path.basename(cert)
        cli = self.getCLIInstance()
        certs = cli.execute("pool-certificate-list").split()
        if name in certs:
            xenrt.TEC().logverbose("Certificate is installed on %s." % (self.getName()))
            return True
        else:
            xenrt.TEC().logverbose("Certificate is not installed on %s." % (self.getName()))
            return False

    def installPEM(self, pem, waitForXapi=False):
        self.execdom0("service xapi stop || true")
        self.execdom0("pkill stunnel || true")
        self.execdom0("[ ! -e /etc/xensource/xapi-ssl.pem.orig ] && cp /etc/xensource/xapi-ssl.pem /etc/xensource/xapi-ssl.pem.orig || true")
        sftp = self.sftpClient()
        sftp.copyTo(pem, "/etc/xensource/xapi-ssl.pem")
        sftp.close()
        self.execdom0("service xapi start")
        if waitForXapi:
            self.waitForXapi(600, desc="xapi startup after SSL certificate installation")
        else:
            xenrt.sleep(120)

    def uninstallPEM(self, onlyIfOriginalExists=False, waitForXapi=False):
        self.execdom0("service xapi stop || true")
        self.execdom0("pkill stunnel || true")
        if onlyIfOriginalExists:
            self.execdom0("[ -e /etc/xensource/xapi-ssl.pem.orig ] && rm -f /etc/xensource/xapi-ssl.pem || true")
        else:
            self.execdom0("rm -f /etc/xensource/xapi-ssl.pem")
        self.execdom0("[ -e /etc/xensource/xapi-ssl.pem.orig ] && cp /etc/xensource/xapi-ssl.pem.orig /etc/xensource/xapi-ssl.pem || true")
        self.execdom0("service xapi start")
        if waitForXapi:
            self.waitForXapi(600, desc="xapi startup after SSL certificate uninstallation")
            xenrt.sleep(30)
        else:
            xenrt.sleep(120)

    def isPEMInstalled(self, pem):
        if self.execdom0("ls /etc/xensource/xapi-ssl.pem", retval="code"):
            hosthash = self.execdom0("md5sum /etc/xensource/xapi-ssl.pem").split()[0]
            comphash = xenrt.command("md5sum %s" % (pem)).split()[0]
            if hosthash == comphash:
                xenrt.TEC().logverbose("Checked PEM is installed on %s." % (self.getName()))
                return True
            else:
                xenrt.TEC().logverbose("Checked PEM is not installed on %s." % (self.getName()))
                return False
        else:
            xenrt.TEC().logverbose("No PEM is installed on %s." % (self.getName()))
            return False

    def getManagementBridge(self):
        network = self.parseListForOtherParam("pif-list",
                                              "management",
                                              "true",
                                              "network-uuid",
                                              "host-uuid=%s" % (self.getMyHostUUID()))
        return self.genParamGet("network", network, "bridge")

    def getStorageBridge(self, sr=None):
        if not sr:
            sr = self.lookupDefaultSR()
        pbds = self.minimalList("pbd-list", args="sr-uuid=%s" % (sr))
        server = map(lambda x:self.genParamGet("pbd", x, "device-config", "server"), pbds)[0]
        return self.getInterfaceForDestination(server)

    def configureCCFirewall(self, includeTestSpecific=True):
        if xenrt.TEC().lookup("CC_SKIP_FWCONFIG", False, boolean=True):
            xenrt.TEC().warning("Skipping Firewall config due to CC_SKIP_FWCONFIG setting")
            return
        self.execdom0("iptables -P INPUT ACCEPT")
        self.execdom0("iptables -P FORWARD ACCEPT")
        self.execdom0("iptables -P OUTPUT ACCEPT")
        self.execdom0("iptables -F")
        self.execdom0("iptables -X")
        self.execdom0("iptables -A INPUT -i %s -p tcp --sport 1024:65535 "
                      "--dport 443 -m state --state NEW -j ACCEPT" %
                      (self.getManagementBridge()))
        if includeTestSpecific:
            # Test specific: Enable port 22 (SSH).
            self.execdom0("iptables -A INPUT -i %s -p tcp --sport 1024:65535 "
                          "--dport 22 -m state --state NEW -j ACCEPT" %
                          (self.getManagementBridge()))
            # Test specific: Enable port 80 (unsecured HTTP).
            self.execdom0("iptables -A INPUT -i %s -p tcp --sport 1024:65535 "
                          "--dport 80 -m state --state NEW -j ACCEPT" %
                          (self.getManagementBridge()))
        self.execdom0("iptables -A INPUT -i %s -p tcp "
                      "-m state --state RELATED,ESTABLISHED -j ACCEPT" %
                      (self.getManagementBridge()))
        self.execdom0("iptables -A INPUT -i %s -j DROP" %
                      (self.getManagementBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 443 -m state --state NEW -j ACCEPT" %
                      (self.getManagementBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 7279 -m state --state NEW -j ACCEPT" %
                      (self.getManagementBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 27000 -m state --state NEW -j ACCEPT" %
                      (self.getManagementBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 123 -m state --state NEW -j ACCEPT" %
                      (self.getManagementBridge()))
        if includeTestSpecific:
            # Test specific: Enable HTTP to controller (for Linux distros)
            self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 80 -d %s "
                          "-m state --state NEW -j ACCEPT" %
                          (self.getManagementBridge(),
                           xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")))
            # Test specific: Enable NFS to ISO SRs
            isoSRs = []
            isoSR = xenrt.TEC().lookup("EXPORT_ISO_NFS", None)
            if isoSR:
                isoSRs.append(isoSR.split(":")[0])
            staticIsoSR = xenrt.TEC().lookup("EXPORT_ISO_NFS_STATIC", None)
            if staticIsoSR:
                isoSRs.append(staticIsoSR.split(":")[0])
            for i in isoSRs:
                self.execdom0("iptables -A OUTPUT -o %s -p udp --dport 111 "
                              "-d %s -m state --state NEW -j ACCEPT" %
                              (self.getManagementBridge(),i))
                self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 111 "
                              "-d %s -m state --state NEW -j ACCEPT" %
                              (self.getManagementBridge(),i))
                self.execdom0("iptables -A OUTPUT -o %s -p udp --dport 2049 "
                              "-d %s -m state --state NEW -j ACCEPT" %
                              (self.getManagementBridge(),i))
                self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 2049 "
                              "-d %s -m state --state NEW -j ACCEPT" %
                              (self.getManagementBridge(),i))
                self.execdom0("iptables -A OUTPUT -o %s -p udp --dport 26345:26348 "
                              "-d %s -m state --state NEW -j ACCEPT" %
                              (self.getManagementBridge(),i))
                self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 26345:26348 "
                              "-d %s -m state --state NEW -j ACCEPT" %
                              (self.getManagementBridge(),i))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp "
                      "-m state --state RELATED,ESTABLISHED -j ACCEPT" %
                      (self.getManagementBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -j DROP" %
                      (self.getManagementBridge()))
        # Storage rules.
        self.execdom0("iptables -A INPUT -i %s -p tcp "
                      "-m state --state RELATED,ESTABLISHED -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A INPUT -i %s -j DROP" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p udp --dport 111 "
                      "-m state --state NEW -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 111 "
                      "-m state --state NEW -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p udp --dport 2049 "
                      "-m state --state NEW -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 2049 "
                      "-m state --state NEW -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p udp --dport 26345:26348 "
                      "-m state --state NEW -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -p tcp --dport 26345:26348 "
                      "-m state --state NEW -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s "
                      "-m state --state RELATED,ESTABLISHED -j ACCEPT" %
                      (self.getStorageBridge()))
        self.execdom0("iptables -A OUTPUT -o %s -j DROP" %
                      (self.getStorageBridge()))
        # Save the configuration
        self.iptablesSave()

    def configureForCC(self):
        """Configure the host in Common Criteria mode"""
        if self.hasLocalSR():
            self.removeLocalSR()
            cli = self.getCLIInstance()
            cli.execute("pool-sync-database")
        if not self.isCCEnabled():
            self.enableCC()

    def isConfiguredForCC(self):
        """Verify a host is configued in Common Criteria mode"""
        xenrt.TEC().logverbose("Checking if host %s is configured for CC." %
                               (self.getName()))
        if self.hasLocalSR():
            xenrt.TEC().warning("CC violation: %s has a local SR." %
                                (self.getName()))
            return False
        if self.getLicenseDetails()["edition"] != "platinum":
            xenrt.TEC().warning("CC violation: %s has wrong license." %
                                (self.getName()))
            return False
        # We don't currently test the firewall config
        xenrt.TEC().warning("CC warning: Firewall configuration untested on %s." %
                            (self.getName()))
        if not self.isCCEnabled():
            xenrt.TEC().warning("CC violation: Restrictions disabled on %s." %
                                (self.getName()))
            return False
        if not self.isSSLVerificationEnabled():
            xenrt.TEC().warning("CC violation: SSL verification not enabled.")
            return False
        xenrt.TEC().logverbose("Host %s is configured for CC." %
                               (self.getName()))
        return True

    ########################################################################
    # CPU Methods

    def getCPUInfo(self):
        cli = self.getCLIInstance()
        info = cli.execute("host-cpu-info","host-uuid=%s" % (self.getMyHostUUID()))
        return xenrt.parseLayeredConfig(info, {'sep':'\n', 'sub':':', 'post':dict})

    def getCPUFeatures(self):
        cli = self.getCLIInstance()
        return cli.execute("host-get-cpu-features","host-uuid=%s" % (self.getMyHostUUID())).strip()

    def setCPUFeatures(self, features):
        cpuinfo = self.getCPUInfo()
        cli = self.getCLIInstance()
        cli.execute("host-set-cpu-features", args="host-uuid=%s features=%s" % (self.getMyHostUUID(),features))
        # Verify setting is correct
        ncpuinfo = self.getCPUInfo()
        assert ncpuinfo['physical_features'] == cpuinfo['physical_features']
        assert ncpuinfo['features'] == cpuinfo['features']
        if ncpuinfo['features_after_reboot'] == features:
            xenrt.TEC().logverbose("features after reboot is set correctly")
        else:
            raise xenrt.XRTFailure("features after reboot is set wrong",
                                   data = features)
        extlinux = self.execdom0('cat /boot/extlinux.conf')
        if (ncpuinfo['features_after_reboot'] != ncpuinfo['physical_features']):
            # We should set some CPU features in Xen
            if (extlinux.find('cpuid_mask') >= 0):
                xenrt.TEC().logverbose("CPU masking is set correctly in xen")
                self.execdom0("sync")
            else:
                raise xenrt.XRTFailure("CPU masking is not set in Xen cmd")
        else:
            masks = re.findall('cpuid_mask', extlinux)
            allowedmasks = re.findall('cpuid_mask_xsave_eax=0', extlinux) # This one is statically set in some releases
            if len(masks) > len(allowedmasks):
                raise xenrt.XRTFailure("Non-static CPU masking option is in Xen cmd")
            else:
                xenrt.TEC().logverbose("No extra CPU masking set in Xen cmd")

    def resetCPUFeatures(self, reboot=True):
        cpuinfo = self.getCPUInfo()
        cli = self.getCLIInstance()
        cli.execute("host-reset-cpu-features", "host-uuid=%s" % (self.getMyHostUUID()))
        ncpuinfo = self.getCPUInfo()
        if cpuinfo['physical_features'] == ncpuinfo['physical_features'] \
           == ncpuinfo['features_after_reboot']:
            xenrt.TEC().logverbose("features reset correctly")
        else:
            raise xenrt.XRTFailure("features reset wrongly",
                                   data = (cpuinfo, ncpuinfo))
        extlinux = self.execdom0('cat /boot/extlinux.conf')
        masks = re.findall('cpuid_mask', extlinux)
        allowedmasks = re.findall('cpuid_mask_xsave_eax=0', extlinux)
        if len(masks) > len(allowedmasks):            
            raise xenrt.XRTFailure("CPU masking option is in Xen cmd")
        else:
            xenrt.TEC().logverbose("No masking option is found in Xen cmd")
        if reboot and ncpuinfo['features'] != ncpuinfo['features_after_reboot']:
            self.reboot()

    def deleteSecret(self, uuid):
        cli = self.getCLIInstance()
        cli.execute('secret-destroy', 'uuid=%s' % uuid)
    
    def deleteAllSecrets(self):
        cli = self.getCLIInstance()
        uuids = self.minimalList('secret-list')
        for uuid in uuids:
            cli.execute('secret-destroy', 'uuid=%s' % uuid)

    def createSecret(self, value):
        cli = self.getCLIInstance()
        msg = cli.execute('secret-create', 'value=%s' % value)
        return msg.strip()

    def modifySecret(self, uuid, newvalue):
        cli = self.getCLIInstance()
        cli.execute('secret-param-set', 'uuid=%s value=%s' 
                    % (uuid, newvalue))

    def getSecrets(self, value):
        cli = self.getCLIInstance()
        uuids = cli.execute('secret-list', 'value=%s' % value, minimal=True)
        return uuids.split(',')

    def installLicenseServerGuest(self, name=None, windows = False, host=None):
        if not name:
            name = xenrt.randomGuestName()
        if windows:
            g = self.createGenericWindowsGuest(name=name)
        else:
            g = self.guestFactory()(\
                name, "NO_TEMPLATE",
                password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
            g.host = self
            xenrt.TEC().registry.guestPut(name, g)
            g.importVM(self, xenrt.TEC().getFile(xenrt.TEC().lookup("LICENSE_SERVER_XVA")))
            g.windows = False
            g.lifecycleOperation("vm-start",specifyOn=True)
            # Wait for the VM to come up.
            xenrt.TEC().progress("Waiting for the VM to enter the UP state")
            g.poll("UP", pollperiod=5)
            xenrt.sleep(120)
        
        g.getV6LicenseServer(host=host)
        return g

    def enableDefaultADAuth(self):
        # 1. Join the domain (supported pre-MNR)
        Host.enableDefaultADAuth(self)

        # 2. Associate users with roles
        users = xenrt.TEC().lookup(["AD_CONFIG", "USERS"])
        groups = xenrt.TEC().lookup(["AD_CONFIG", "GROUPS"])
        # Convert the users into a dictionary of {role:(user, password)}
        userdict = dict((x, tuple(users[x].split(":", 1))) for x in users.keys())
        groupdict = dict((x, tuple(groups[x].split(":", 2))) for x in groups.keys())


        roles = {"POOL_ADMIN": "pool-admin",
                 "POOL_OPERATOR": "pool-operator",
                 "VM_POWER_ADMIN": "vm-power-admin",
                 "VM_ADMIN": "vm-admin",
                 "VM_OPERATOR": "vm-operator",
                 "READ_ONLY": "read-only"}

        cli = self.getCLIInstance()
        for r in roles.keys():
            uuid = cli.execute("subject-add", "subject-name=%s" % userdict[r][0]).strip()
            cli.execute("subject-role-add", "role-name=%s uuid=%s" % (roles[r], uuid))
            uuid = cli.execute("subject-add", "subject-name=%s" % groupdict[r][0]).strip()
            cli.execute("subject-role-add", "role-name=%s uuid=%s" % (roles[r], uuid))

#############################################################################

class BostonHost(MNRHost):
    """Represents a Boston host"""

    def guestFactory(self):
        return xenrt.lib.xenserver.guest.BostonGuest

    def writeToConsole(self, domid, str, tty=None, retlines=0, cuthdlines=0):
        """Write str into the domain's main console stdin"""
        """and wait for retlines in stdout"""
        out = self.execdom0("echo -e -n '%s' | %s/consolewrite.py %s %u %u " % (str,xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),domid,retlines,cuthdlines))
        return out

    def reboot(self,sleeptime=120,forced=False,timeout=600):
        """Reboot the host and verify it boots"""
        Host.reboot(self,forced=forced,timeout=timeout, sleeptime=sleeptime)
        self.waitForXapiStartup()

    def createNetwork(self, name="XenRT bridge"):
        cli = self.getCLIInstance()
        args = []
        args.append("name-label=\"%s\"" % (name))
        args.append("name-description=\"Created by XenRT\"")
        nwuuid = cli.execute("network-create", string.join(args)).strip() 

        return nwuuid

    def createVLAN(self, vlan, bridge, nic=None, pifuuid=None):
        """Create a new VLAN on the host and return the untagged PIF UUID."""
        if not pifuuid:
            pifuuid = self.parseListForUUID("pif-list VLAN=-1 host-uuid=%s" %
                                            (self.getMyHostUUID()),
                                            "device",
                                            nic)
        cli = self.getCLIInstance()
        args = []
        args.append("network-uuid=%s" % (bridge))
        args.append("vlan=%u" % (vlan))
        args.append("pif-uuid=%s" % (pifuuid))
        r = cli.execute("vlan-create", string.join(args)).strip()
        
        cli.execute("pif-plug uuid=%s" % (r))
        return r

    def checkVLAN(self, vlan, nic="eth0"):
        """Check VLAN has been installed correctly."""
        
        if self.special['Network subsystem type'] == "linux":
            return Host.checkVLAN(self, vlan, nic)

        hostuuid = self.getMyHostUUID()
        vlanuuid = self.parseListForUUID("pif-list", "VLAN", vlan,
                                         args="host-uuid=%s" % hostuuid)

        networkuuid = self.genParamGet("pif", vlanuuid, "network-uuid")
        bridge = self.genParamGet("network", networkuuid, "bridge")
        device = self.genParamGet("pif", vlanuuid, "device")

        parent_pifuuid = self.parseListForUUID("pif-list", "device", nic,
                                               args="host-uuid=%s VLAN=-1" % 
                                               (hostuuid))
        
        parent_netuuid = self.genParamGet("pif", parent_pifuuid, 'network-uuid')
        parent_br = self.genParamGet("network", parent_netuuid, "bridge")
        
        if device != nic:
            raise xenrt.XRTFailure("NIC mismatch %s != %s." % (device, nic))

        try:
            actual_vlan = int(self.execdom0("ovs-vsctl br-to-vlan %s" % bridge).strip())
            if vlan != actual_vlan:
                raise xenrt.XRTFailure("VLAN mismatch %u != %u." % (actual_vlan, vlan))
        except:
            xenrt.TEC().warning("Unable to determine VLAN for fake-bridge interface %s." % bridge)

        try:
            actual_parent = self.execdom0("ovs-vsctl br-to-parent %s" % bridge).strip()
            if parent_br != actual_parent:
                raise xenrt.XRTFailure("Bridge parent mismatch %s != %s." % (parent_br, actual_parent))
        except:
            xenrt.TEC().warning("Unable to determine parent of fake-bridge interface %s." % bridge)

    def getBondInfo(self,bond):
        """Gets information about a network bond"""

        if self.special['Network subsystem type'] == "linux":
            return Host.getBondInfo(self,bond)

        lines = self.vswitchAppCtl("bond/show %s" % bond).split("\n")
        xenrt.TEC().logverbose("bond/show = %s" % lines)

        info = {}
        slaves = {}
        
        info['slb'] = {}
        info['mode'] = None # bond modes are not yet supported on the vSwitch
        info['load'] = {}
        slave = None
        for line in lines:
            if line.startswith("updelay: ") or \
               line.startswith("downdelay:" ) or \
               line.startswith("next rebalance: "):
                # uninteresting fields
                pass
            elif line.startswith("bond_mode: "):
                _,info['mode'] = line.split()
            elif line.startswith("lacp_negotiated: "):
                _,info['lacp'] = line.split()
            elif line.startswith("lacp_status: "):
                _,info['lacp'] = line.split()
            elif line.startswith("slave "):
                statusmap = {'enabled': 'up', 'disabled': 'down'}
                _,slave,status = line.split()
                slave = slave.rstrip(":")
                info['load'][slave] = 0

                assert(not slaves.has_key(slave))
                slaves[slave] = {}
                uuid = self.parseListForUUID("pif-list VLAN=-1 host-uuid=%s" %
                                             (self.getMyHostUUID()),
                                             "device", slave)
                MAC = self.genParamGet("pif", uuid, "MAC")
                slaves[slave]['status'] = statusmap[status]
                slaves[slave]['hwaddr'] = MAC
            elif line.startswith("\tactive slave"):
                assert(slave)
                info['active_slave'] = slave
            elif line.startswith("\tupdelay expires"):
                assert(slave)
                slaves[slave]['status'] = "down"
            elif line.startswith("\tdowndelay expires"):
                assert(slave)
                slaves[slave]['status'] = "up"
            elif line[:6] == "\thash ":
                assert(slave)
                _,hash,_ = line.split(None, 2)
                hash = hash.rstrip(":")
                info['slb'][int(hash)] = slave
                load = re.search(":\s(.*)\skB",line)
                load = int(load.group(1))
                info['load'][slave]=info['load'][slave] + load
            elif line[:2] == "\t\t":
                assert(re.match("[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}$", line[2:]))
            
        info['slaves'] = slaves.keys()
        
        return (info,slaves)

    # Boston has a redesign of Bond creation such that pif-reconfigure-ip
    # and host-management-reconfigure are no longer required to be called.
    def createBond(self,pifs,dhcp=False,management=False,network=None,mode=None,ignorePifCarrierFor=[]):
        """Create a bond device using the given pifs"""
        
        #Check the switch limit on maximum NICs a lacp bond can have
        switch = None
        if mode == "lacp":
            switch = xenrt.lib.switch.createSwitchForPifs(self, pifs)
            if len(pifs) > switch.MAX_PORTS_PER_LAG:
                raise xenrt.XRTError("The number of NICs in the bond exceed the switch limit of %d"  % (switch.MAX_PORTS_PER_LAG))
        
        xenrt.TEC().logverbose("BostonHost::createBond")
        if not network:
            network = self.createNetwork()

        cli = self.getCLIInstance()
        args = []
        args.append("network-uuid=%s" % (network))
        args.append("pif-uuids=%s" % (string.join(pifs,",")))
        if mode:
            args.append("mode=%s" % (mode))

        # Check the PIFs are not already part of a bond CA-77764
        pifsAlreadyInBond = [pif for pif in pifs if xenrt.isUUID(self.genParamGet("pif",pif,"bond-slave-of"))]
        if len(pifsAlreadyInBond) > 0:
            raise xenrt.XRTError("Asked to create bond including PIFs which "
                                 "are already part of a bond!",
                                 pifsAlreadyInBond)
       
        # Check PIFs are having carrier = true ( PIFs are plugged )
        pifsToCheck = set(pifs) - set(ignorePifCarrierFor)
        pifsWithCarrierFalse = [pif for pif in pifsToCheck if self.genParamGet("pif",pif,"carrier").strip() != "true"]
        
        if len(pifsWithCarrierFalse) > 0:
            # Attempting to enable the switch port with warning.
            for pif in pifsWithCarrierFalse:
                warning("[%s] PIF has carrier = false, attempting to enable switch port." % pif)
                mac = self.genParamGet("pif", pif, "MAC")
                self.enableNetPort(mac)
            
            xenrt.sleep(30)
            
            # If we still have any pif having carrier = false means that pif is unplugged. raise XRTError
            pifsWithCarrierFalse = [pif for pif in pifsToCheck if self.genParamGet("pif",pif,"carrier").strip() != "true"]
            if len(pifsWithCarrierFalse) > 0:
                raise xenrt.XRTError("Asked to create bond including %s PIFs which "
                                    "have carrier = false: %s. Possibly previous test"
                                    "case failed to do clean up and left pifs unplugged." 
                                    % (len(pifsWithCarrierFalse),pifsWithCarrierFalse))
        
        existingBonds = self.getBonds()
        try:
            cli.execute("bond-create",string.join(args)).strip()
        except:
            pass # bond-create may do host-management-reconfigure and therefore break the connection
        finally:
            xenrt.sleep(120) 

        self.waitForXapi(300, desc="Xapi reachability after bond-create")
        currentBonds = self.getBonds()
        newBonds = set(currentBonds) - set(existingBonds)
        if len(newBonds) < 1:
            raise xenrt.XRTError("No new bonds found after bond-create")
        bondUUID = newBonds.pop()

        if not xenrt.isUUID(bondUUID):
            raise xenrt.XRTError("Couldn't find UUID after creating bond")

        if mode == 'lacp':
            switch.setLACP()  #setting LACP on the switch,
            xenrt.sleep(60)  #Adding wait to prevent a connectivity blip
        
        # Find the PIF
        pifUUID = self.parseListForUUID("pif-list", "bond-master-of", bondUUID)

        # check that specified pifs are indeed the bond slaves 
        slaves = self.genParamGet("bond", bondUUID, "slaves").split("; ")
        if (set(slaves)-set(pifs)):
            log("Specified pifs to bond: %s" % pifs)
            log("Bond slaves found: %s" % slaves)
            raise xenrt.XRTError("Unexpected mismatch between specified pifs and bond slaves")
    
        bridge = self.genParamGet("network", network, "bridge")
        device = self.genParamGet("pif", pifUUID, "device")

        return (bridge, device)

    def _setPifsForLacp(self, pifs):
        switch = xenrt.lib.switch.createSwitchForPifs(self, pifs)
        switch.setLACP()
        # Turning on LACP results in a delay before the host is reachable again ( CA-165518 )
        self.waitForSSH(120, desc="Host reachability after enabling LACP on switch")

    def _unsetPifsForLacp(self, pifs):
        switch = xenrt.lib.switch.createSwitchForPifs(self, pifs)
        switch.unsetLACP()
        # Turning off LACP results in a delay before the host is reachable again (CA-71411, CA-76500)
        self.waitForSSH(120, desc="Host reachability after disabling LACP on switch")

    def removeBond(self, bonduuid, dhcp=False, management=False):
        """Remove the specified bond device and replumb the management
        interface to the first raw PIF"""

        xenrt.TEC().logverbose("BostonHost::removeBond")
        cli = self.getCLIInstance()

        # List the PIFs used by the bond
        pifs = self.genParamGet("bond", bonduuid, "slaves").split("; ")

        # Get the bond device for a later check
        bpif = self.genParamGet("bond", bonduuid, "master")
        bdevice = self.genParamGet("pif", bpif, "device")
        bnetwork = self.genParamGet("pif", bpif, "network-uuid")
        bmode = self.genParamGet("bond", bonduuid, "mode")

        switchForPifs = None
        if bmode == 'lacp':
            switchForPifs = xenrt.lib.switch.createSwitchForPifs(self, pifs)


        args = []
        args.append("uuid=%s" % (bonduuid))
        try:
            cli.execute("bond-destroy", string.join(args), timeout=60)
        except:
            pass
        finally:
            if bmode == 'lacp':
                # remove LACP set-up on the switch
                switchForPifs.unsetLACP()
            xenrt.sleep(120) # CA-57304


        if management:
            xenrt.sleep(120)

        # Check the bond has gone away

        try:
            self.getBondInfo(bdevice)
            raise xenrt.XRTFailure("Bond config still exists for %s" % bdevice)
        except:
            pass

        cli.execute("network-destroy", "uuid=%s" % (bnetwork))

        mpif = ''
        if management:
            mpif = self.minimalList("pif-list", args="management=true host-uuid=%s" % (self.getMyHostUUID()))[0]
        else:
            for pif in pifs:
                ip = self.genParamGet("pif", pif, "IP")
                if len(ip) > 0:
                    mpif = pif
                    break
                
        if mpif:
            network = self.genParamGet("pif", mpif, "network-uuid")
            bridge = self.genParamGet("network", network, "bridge")
            device = self.genParamGet("pif", mpif, "device")
        else:
            bridge = None
            device = None
        return (bridge, device)
        
    def enableVirtualFunctions(self):

        out = self.execdom0("grep -v '^#' /etc/modprobe.d/ixgbe 2> /dev/null; echo -n ''").strip()
        if len(out) > 0:
            return

        numPFs = int(self.execdom0('lspci | grep 82599 | wc -l').strip())
        #we check ixgbe version so as to understand netsclaer VPX specific - NS drivers: in which case, configuration differs slightly. 
        ixgbe_version = self.execdom0("modinfo ixgbe | grep 'version:        '") 
        if numPFs > 0:
            if (re.search("NS", ixgbe_version.split()[1])):
                maxVFs = "63" + (",63" * (numPFs - 1))
            else:
                maxVFs = "40"
            self.execdom0('echo "options ixgbe max_vfs=%s" > "/etc/modprobe.d/ixgbe"' % (maxVFs))

            self.reboot()
            self.waitForSSH(300, desc="host reboot after enabling virtual functions")

    def createNetworkTopology(self, topology):
        """Create the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        if not physList: 
            xenrt.TEC().logverbose("Empty network configuration.")
            return

        cli = self.getCLIInstance()

        vlanpifs = []

        # configure single nic non vlan jumbo networks
        requiresReboot = False
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            # create only on single nic non valn nets
            if len(nicList) == 1  and len(vlanList) == 0:
                pif = self.getNICPIF(nicList[0])
                nwuuid = self.genParamGet("pif", pif, "network-uuid")               
                if jumbo == True:
                    cli.execute("network-param-set uuid=%s MTU=9000" % (nwuuid))
                    requiresReboot = True
                elif jumbo != False:
                    cli.execute("network-param-set uuid=%s MTU=%s" % (nwuuid, jumbo))
                    requiresReboot = True

        # Create all bonds
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            if len(nicList) > 1:
                if bondMode == None:
                    if xenrt.TEC().lookup("NO_SLB", False, boolean=True):
                        bondMode = "active-backup"
                    else:
                        bondMode = 'balance-slb'
                xenrt.TEC().logverbose("Creating bond on %s using %s" %
                                       (network, str(nicList)))
                netname = "%s bond of %s" % (network,
                                             string.join(map(str, nicList)))
                # See if we have a bond network already
                nwuuids = self.minimalList("network-list",
                                     "uuid",
                                     "name-label=\"%s\"" % (netname))
                existing = False
                if len(nwuuids) > 0:
                    xenrt.TEC().logverbose(" ... bond network already exists")
                    nwuuid = nwuuids[0]
                    existing = True
                else:
                    args = []
                    args.append("name-label=\"%s\"" % (netname))
                    args.append("name-description=\"Created by XenRT\"")
                    nwuuid = cli.execute("network-create",
                                         string.join(args)).strip()

                # Ensure MTU is correct ("jumbo" can be True, False or a number...)
                currentMTU = self.genParamGet("network", nwuuid, "MTU")
                if jumbo == True and currentMTU != "9000":
                    self.genParamSet("network", nwuuid, "MTU", "9000")
                    if existing: requiresReboot = True
                elif jumbo != False and currentMTU != jumbo:
                    self.genParamSet("network", nwuuid, "MTU", str(jumbo))
                    if existing: requiresReboot = True
                elif currentMTU != "1500":
                    self.genParamSet("network", nwuuid, "MTU", "1500")
                    if existing: requiresReboot = True
                else:
                    xenrt.TEC().logverbose(" ... current MTU is correct")

                # See if we have a bond PIF already
                pifuuid = self.parseListForUUID("pif-list", "network-uuid", nwuuid)
                existing = False
                if pifuuid != '':
                    xenrt.TEC().logverbose(" ... bond PIF already exists")
                    existing = True
                    bonduuid = self.genParamGet("pif", pifuuid, "bond-master-of")
                    currentMode = self.genParamGet("bond", bonduuid, "mode")
                    if currentMode != bondMode:
                        xenrt.TEC().logverbose(" ... but is the wrong mode, changing...")
                        if currentMode == "lacp":
                            # Was LACP, turn off switch support prior to changing mode
                            pifs = self.genParamGet("bond", bonduuid, "slaves").split("; ")
                            self._unsetPifsForLacp(pifs)
                        cli.execute("bond-set-mode", "uuid=%s mode=%s" % (bonduuid, bondMode))
                        if bondMode == "lacp":
                            # Becoming LACP, change mode then set up switch support
                            pifs = self.genParamGet("bond", bonduuid, "slaves").split("; ")
                            self._setPifsForLacp(pifs)
                    else:
                        xenrt.TEC().logverbose(" ... and is the correct mode")
                else:
                    pifs = []
                    for nic in nicList:
                        pif = self.getNICPIF(nic)
                        pifs.append(pif)
                    args = []
                    args.append("pif-uuids=%s" % (string.join(pifs, ",")))
                    args.append("network-uuid=%s" % (nwuuid))
                    args.append("mode=%s" % bondMode)
                    existingBonds = self.getBonds()
                    try:
                        cli.execute("bond-create", string.join(args)).strip()
                    except:
                        pass # bond-create may do host-management-reconfigure and therefore break the connection
                    finally:
                        xenrt.sleep(120)

                    currentBonds = self.getBonds()
                    bonduuid = (set(currentBonds) - set(existingBonds)).pop()

                    # Enable LACP *after* creating the bond
                    if bondMode == "lacp":
                        self._setPifsForLacp(pifs)

                    # check that specified pifs are indeed the bond slaves 
                    slaves = self.genParamGet("bond", bonduuid, "slaves").split("; ")
                    if (set(slaves)-set(pifs)):
                        log("Specified pifs to bond: %s" % pifs)
                        log("Bond slaves found: %s" % slaves)
                        raise xenrt.XRTError("Mismatch between requested and specified bond slaves")
                        
                    pifuuid = self.parseListForUUID("pif-list", "bond-master-of", bonduuid)

        # Create all VLANs
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            for v in vlanList:
                vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                xenrt.TEC().logverbose("Creating VLAN %s on %s (%s)" %
                                       (vnetwork, network, str(nicList)))
                netname = "VLAN %s on %s %s" % (vnetwork,
                                                network,
                                                string.join(map(str, nicList)))
                # See if we have one already
                n = self.minimalList("network-list",
                                     "name-label",
                                     "name-label=\"%s\"" % (netname))
                if len(n) > 0:
                    xenrt.TEC().logverbose(" ... already exists")
                else:
                    vid, subnet, netmask = self.getVLAN(vnetwork)
                    if len(nicList) == 1:
                        # raw PIF
                        pif = self.getNICPIF(nicList[0])
                    else:
                        # bond
                        lpif = self.getNICPIF(nicList[0])
                        bond = self.genParamGet("pif", lpif, "bond-slave-of")
                        pif = self.genParamGet("bond", bond, "master")
                    args = []
                    args.append("name-label=\"%s\"" % (netname))
                    args.append("name-description=\"Created by XenRT\"")
                    if jumbo == True:
                        args.append("MTU=9000")
                    elif jumbo != False:
                        args.append("MTU=%d" % jumbo) 
                    nwuuid = cli.execute("network-create",
                                         string.join(args)).strip()
                    args = []
                    args.append("pif-uuid=%s" % (pif))
                    args.append("vlan=%u" % (vid))
                    args.append("network-uuid=%s" % (nwuuid))
                    p = cli.execute("vlan-create", string.join(args)).strip()
                    cli.execute("pif-plug uuid=%s" % (p))
                    vlanpifs.append(p)

        self._addIPConfigToNetworkTopology(physList)

        # CA-22381 Plug any VLANs we created
        for pif in vlanpifs:
            try:
                cli.execute("pif-plug", "uuid=%s" % (pif))
            except Exception, e:
                xenrt.TEC().warning("Exception plugging VLAN PIF %s: %s" %
                                    (pif, str(e)))

        # Only reboot if required and once while physlist is processed
        if requiresReboot == True:
            self.reboot()


    def _addIPConfigToNetworkTopology(self, physList):
        xenrt.TEC().logverbose("BostonHost::_addIPConfigToNetworkTopology")
        cli = self.getCLIInstance()

        # Trial workaround for CA-87053
        if xenrt.TEC().lookup("WORKAROUND_CA87053", False, boolean=True):
            xenrt.TEC().warning("Using CA-87053 workaround")
            self.execdom0("echo 1 > /proc/sys/net/ipv4/conf/all/arp_announce")

        # Put IP addresses on all interfaces that need them. Note bridges
        # that can take VMs
        managementPIF = None
        IPPIFs = []
        staticPIFs = {}
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            if mgmt or storage:
                xenrt.TEC().logverbose("BostonHost::Putting IP on %s (%s)" %
                                       (network, str(nicList)))
                if len(nicList) == 1:
                    # raw PIF
                    pif = self.getNICPIF(nicList[0])
                else:
                    # bond
                    lpif = self.getNICPIF(nicList[0])
                    bond = self.genParamGet("pif", lpif, "bond-slave-of")
                    pif = self.genParamGet("bond", bond, "master")
                if mgmt and not storage:
                    mode = mgmt
                elif storage and not mgmt:
                    mode = storage
                else:
                    if mgmt == storage:
                        mode = mgmt
                    else:
                        raise xenrt.XRTError(\
                            "Incompatible modes for storage amd mgmt "
                            "functions of this PIF: %s, %s" % (storage, mgmt),
                            "%s (%s)" % (network, str(nicList)))
                current = self.genParamGet("pif", pif, "IP-configuration-mode")
                current = current.lower()
                xenrt.TEC().logverbose("Current mode %s, want %s" %
                                       (current, mode))
                if current == mode:
                    xenrt.TEC().logverbose(" ... already exists")
                elif mode == "dhcp":
                    cli.execute("pif-reconfigure-ip",
                                "uuid=%s mode=dhcp" % (pif))
                elif mode == "static":
                    ip, netmask, gateway = \
                        self.getNICAllocatedIPAddress(nicList[0])
                    args = []
                    args.append("uuid=%s" % (pif))
                    args.append("mode=static")
                    args.append("IP=%s" % (ip))
                    args.append("netmask=%s" % (netmask))
                    staticPIFs[pif] = (ip, netmask)
                    args.append("gateway=%s" % (gateway))
                    if mgmt:
                        dns = self.lookup(["NETWORK_CONFIG",
                                           "DEFAULT",
                                           "NAMESERVERS"], None)
                        if dns:
                            args.append("DNS=%s" % (dns))
                    try:
                        cli.execute("pif-reconfigure-ip", string.join(args))
                    except:
                        pass
                    xenrt.sleep(5)
                else:
                    raise xenrt.XRTError("Unknown PIF mode '%s'" % (mode),
                                         "%s (%s)" % (network, str(nicList)))
                if storage:
                    self.genParamSet("pif", pif, "disallow-unplug", "true")
                    cli.execute("pif-plug", "uuid=%s" % (pif))
                IPPIFs.append(pif)
                if mgmt and not managementPIF:
                    managementPIF = (pif, "%s (%s)" % (network, str(nicList)))
            
            if len(nicList) == 1:
                # raw PIF
                pif = self.getNICPIF(nicList[0])
                nwuuid = self.genParamGet("pif", pif, "network-uuid")
            else:
                # bond
                netname = "%s bond of %s" % (network,
                                             string.join(map(str, nicList)))
                nwuuid = self.parseListForUUID("network-list",
                                               "name-label",
                                               netname)
            if vms:
                xenrt.TEC().logverbose("Putting VMs on %s (%s)" %
                                       (network, str(nicList)))

                self.genParamSet("network",
                                 nwuuid,
                                 "other-config",
                                 "true",
                                 "xenrtvms")
                
            if friendlynetname:
                with self._getNetNameLock():
                    self.genParamSet("network", nwuuid, "other-config", friendlynetname, "xenrtnetname")

            for v in vlanList:
                vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                if vmgmt or vstorage:
                    xenrt.TEC().logverbose("bostonHost::Putting IP on %s on %s (%s)" %
                                           (vnetwork, network, str(nicList)))
                    vid, subnet, netmask = self.getVLAN(vnetwork)
                    if len(nicList) == 1:
                        # raw PIF
                        tpif = self.getNICPIF(nicList[0])
                    else:
                        # bond
                        lpif = self.getNICPIF(nicList[0])
                        bond = self.genParamGet("pif", lpif, "bond-slave-of")
                        tpif = self.genParamGet("bond", bond, "master")
                    pif = self.parseListForOtherParam("vlan-list",
                                                      "tagged-PIF",
                                                      tpif,
                                                      "untagged-PIF",
                                                      "tag=%u" % (vid))
                    if vmgmt and not vstorage:
                        mode = vmgmt
                    elif vstorage and not vmgmt:
                        mode = vstorage
                    else:
                        if vmgmt == vstorage:
                            mode = vmgmt
                        else:
                            raise xenrt.XRTError(\
                                "Incompatible modes for storage amd mgmt "
                                "functions of this PIF: %s, %s" %
                                (vstorage, vmgmt),
                                "%s (%s)" % (vnetwork, str(nicList)))
                    current = self.genParamGet("pif",
                                               pif,
                                               "IP-configuration-mode")
                    current = current.lower()
                    xenrt.TEC().logverbose("Current mode %s, want %s" %
                                           (current, mode))
                    if current == mode:
                        xenrt.TEC().logverbose(" ... already exists")
                    elif mode == "dhcp":
                        cli.execute("pif-reconfigure-ip",
                                    "uuid=%s mode=dhcp" % (pif))
                    elif mode == "static":
                        raise xenrt.XRTError("Static IP VLAN PIFs not supported",
                                             "%s (%s)" % (vnetwork, str(nicList)))
                    else:
                        raise xenrt.XRTError("Unknown PIF mode '%s'" % (mode),
                                             "%s (%s)" % (vnetwork, str(nicList)))
                    if vstorage:
                        self.genParamSet("pif", pif, "disallow-unplug", "true")
                        cli.execute("pif-plug", "uuid=%s" % (pif))
                    IPPIFs.append(pif)
                    if vmgmt and not managementPIF:
                        managementPIF = (pif, "%s on %s (%s)" %
                                         (vnetwork, network, str(nicList)))

                netname = "VLAN %s on %s %s" % (vnetwork,
                                                network,
                                                string.join(map(str, nicList)))
                xenrt.TEC().logverbose("Putting VMs on %s (%s)" %
                                       (network, str(nicList)))
                nwuuid = self.parseListForUUID("network-list",
                                               "name-label",
                                              netname)
                if vvms:
                    self.genParamSet("network",
                                     nwuuid,
                                     "other-config",
                                     "true",
                                     "xenrtvms")
                
                if vfriendlynetname:
                    with self._getNetNameLock():
                        self.genParamSet("network", nwuuid, "other-config", vfriendlynetname, "xenrtnetname")

        # Switch management to the required interface
        if managementPIF:
            pif, desc = managementPIF
            xenrt.TEC().logverbose("Putting management on %s" % (desc))
            # XRT-3934 Check if it's already there
            if self.genParamGet("pif", pif, "management") == "true":
                xenrt.TEC().logverbose(" ... already there")
            else:
                previp = self.getIP()
                pifip = self.genParamGet("pif", pif, "IP")
                if not pifip:
                    raise xenrt.XRTFailure("IP is missing on pif %s, making management pif will result in connectivity loss to host." % pif)
                try:
                    cli.execute("host-management-reconfigure",
                                "pif-uuid=%s" % (pif))
                except:
                    pass
                xenrt.sleep(120)
                newip = self.execdom0("xe host-param-get uuid=%s "
                                      "param-name=address" %
                                      (self.getMyHostUUID())).strip()
                if not newip:
                    raise xenrt.XRTFailure("Failed to get IP of new management interface." )
                self.machine.ipaddr = newip

        # Remove IP addresses from any interfaces that shouldn't have them
        allpifs = self.minimalList("pif-list",
                                   "uuid",
                                   "host-uuid=%s" % (self.getMyHostUUID()))
        for pif in allpifs:
            if pif in IPPIFs:
                if pif != managementPIF[0] and pif in staticPIFs.keys():
                    ip, netmask = staticPIFs[pif]
                    args = []
                    args.append("uuid=%s" % (pif))
                    args.append("mode=static")
                    args.append("IP=%s" % (ip))
                    args.append("netmask=%s" % (netmask))
                    cli.execute("pif-reconfigure-ip", string.join(args))
                continue
            ip = self.genParamGet("pif", pif, "IP-configuration-mode")
            if ip != "None":
                xenrt.TEC().logverbose("Removing IP from %s" % (pif))
                cli.execute("pif-reconfigure-ip", "uuid=%s mode=None" % (pif))

        # Make sure we can still run CLI commands
        try:
            cli.execute("vm-list")
        except:
            raise xenrt.XRTFailure("Failed to run CLI command over new "
                                   "management interface.")

    def checkNetworkTopology(self,
                             topology,
                             ignoremanagement=False,
                             ignorestorage=False,
                             plugtest=False):
        """Verify the topology specified by XML on this host. Takes either
        a string containing XML or a XML DOM node."""

        physList = self._parseNetworkTopology(topology)
        cli = self.getCLIInstance()

        managementPIF = None
        IPPIFs = []

        # Check bonds
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            # As of boston PR-1006 xapi defaults bond-mode to 'balance-slb',
            # this is effectively the same as None
            if bondMode == None:
                if xenrt.TEC().lookup("NO_SLB", False, boolean=True):
                    bondMode="active-backup"
                else:
                    bondMode="balance-slb"
            if len(nicList) > 1:
                xenrt.TEC().logverbose("Checking bond on %s using %s" %
                                       (network, str(nicList)))
                netname = "%s bond of %s" % (network,
                                             string.join(map(str, nicList)))
                # Ensure we only have one network for this bond
                n = self.minimalList("network-list",
                                     "uuid",
                                     "name-label=\"%s\"" % (netname))
                if len(n) == 0:
                    raise xenrt.XRTFailure("Could not find network for '%s'"
                                           % (netname))
                if len(n) > 1:
                    raise xenrt.XRTFailure("Found multiple networks for '%s'"
                                           % (netname))
                # Get the PIF for this network on this host
                pifstring = self.genParamGet("network", n[0], "PIF-uuids")
                if pifstring == "":
                    raise xenrt.XRTFailure("Network '%s' has no PIFs" %
                                           (netname))
                npifs = pifstring.split("; ")
                hpifs = self.minimalList("pif-list",
                                         "uuid",
                                         "host-uuid=%s" %
                                         (self.getMyHostUUID()))
                pif = None
                for p in npifs:
                    if p in hpifs:
                        pif = p
                        break
                if not pif:
                    raise xenrt.XRTFailure("Could not find PIF for '%s' on "
                                           "this host" % (netname),
                                           "host %s" % (self.getName()))
                # Get the bond for this PIF
                bond = self.genParamGet("pif", pif, "bond-master-of")
                if not xenrt.isUUID(bond):
                    raise xenrt.XRTFailure("'%s' bond PIF does not "
                                           "reference bond" % (netname),
                                           "PIF %s -> %s" % (pif, bond))
                mpif = self.genParamGet("bond", bond, "master")
                if mpif != pif:
                    raise xenrt.XRTFailure("Inconsistency in bond master "
                                           "references for '%s'" % (netname),
                                           "PIF %s, master %s" % (pif, mpif))
                # Get the PIFs for the slaves
                pifstring = self.genParamGet("bond", bond, "slaves")
                if pifstring == "":
                    raise xenrt.XRTFailure("Bond for '%s' has no slave PIFs" %
                                           (netname),
                                           "Master PIF %s bond %s" %
                                           (pif, bond))
                spifs = pifstring.split("; ")
                cpifs = map(lambda x:self.getNICPIF(x), nicList)
                for cpif in cpifs:
                    if not cpif in spifs:
                        raise xenrt.XRTFailure("A PIF is missing from the "
                                               "bond for '%s'" % (netname),
                                               "PIF %s" % (cpif))
                for spif in spifs:
                    if not spif in cpifs:
                        raise xenrt.XRTFailure("An extra PIF is in the "
                                               "bond for '%s'" % (netname),
                                               "PIF %s" % (spif))
                for spif in spifs:
                    b = self.genParamGet("pif", spif, "bond-slave-of")
                    if b != bond:
                        raise xenrt.XRTFailure("Inconsistency in bond slave "
                                               "references for '%s'" % (netname),
                                               "PIF %s" % (spif))
                # Make sure the bond PIF has the same MAC as the first NIC
                # in the bond
                bmac = self.genParamGet("pif", pif, "MAC")
                bmac = xenrt.normaliseMAC(bmac)
                nmac = self.getNICMACAddress(nicList[0])
                nmac = xenrt.normaliseMAC(nmac)
                if bmac != nmac:
                    raise xenrt.XRTFailure("Bond '%s' MAC is not the same as "
                                           "the first NIC" % (netname),
                                           "bond %s, NIC %s" % (bmac, nmac))
                # Check the bond mode is set correctly
                try:
                    currentMode = self.genParamGet("bond", bond, "mode")
                except:
                    currentMode = None
                if currentMode != bondMode:
                    raise xenrt.XRTFailure("Bond mode is not set correctly in xapi.",
                                           "Found %s, but should be %s" % (currentMode, bondMode))
                # Check the bond is correctly set up in dom0 (need to be plugged)
                if plugtest or \
                        (mgmt and not ignoremanagement) or \
                        (storage and not ignorestorage):
                    if not ((mgmt and not ignoremanagement) or \
                            (storage and not ignorestorage)):
                        # Won't necessarily be plugged
                        cli.execute("pif-plug", "uuid=%s" % (pif))
                    device = self.genParamGet("pif", pif, "device")
                    (info, slaves) = self.getBondInfo(device)
                    if len(slaves) != len(spifs):
                        raise xenrt.XRTFailure("Incorrect number of interfaces "
                                               "in '%s' bond" % (netname),
                                               "Found %u, should be %u" %
                                               (len(slaves), len(spifs)))
                    for spif in spifs:
                        sdevice = self.genParamGet("pif", spif, "device")
                        if not slaves.has_key(sdevice):
                            raise xenrt.XRTFailure("Device %s missing from '%s' "
                                                   "bond" % (sdevice, netname))
                    if bondMode and (info["mode"] == None or not bondMode in info["mode"]):
                        err = True
                        if bondMode == "lacp":
                            err = info["mode"] != "balance-tcp"
                        elif bondMode == "balance-slb":
                            err = info["mode"] != "source load balancing"
                        
                        if err:
                            raise xenrt.XRTFailure("Bond mode is not set correctly on bond device.",
                                                   "Found %s, but should be %s" % (info["mode"], bondMode))
            else:
                # Not bonded
                netname = "%s (%u)" % (network, nicList[0])
                pif = self.getNICPIF(nicList[0])
                b = self.genParamGet("pif", pif, "bond-master-of")
                if b and xenrt.isUUID(b):
                    raise xenrt.XRTFailure("Non-bonded NIC claims to be a "
                                           "bond master %s" % (netname))
                b = self.genParamGet("pif", pif, "bond-slave-of")
                if b and xenrt.isUUID(b):
                    raise xenrt.XRTFailure("Non-bonded NIC claims to be a "
                                           "bond slave %s" % (netname))

            # Check management and storage IP configuration
            if mgmt:
                if not managementPIF:
                    managementPIF = pif
                mexp = "true"
            else:
                mexp = "false"
            if mgmt or storage:
                IPPIFs.append(pif)
            i = self.genParamGet("pif", pif, "IP-configuration-mode")
            ip = self.genParamGet("pif", pif, "IP")
            if not ignoremanagement:
                m = self.genParamGet("pif", pif, "management")
                if m != mexp:
                    if mexp == "true":
                        msg = "Management not enabled"
                    else:
                        msg = "Management enabled"
                    raise xenrt.XRTFailure("%s on '%s'" % (msg, netname))
                if mgmt and i == "None":
                    raise xenrt.XRTFailure("Management '%s' missing IP "
                                           "configuration" % (netname))
                if mgmt and not ip:
                    # Try again after a brief pause
                    xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                           "checking again...")
                    xenrt.sleep(30)
                    ip = self.genParamGet("pif", pif, "IP")
                    if not ip:
                        raise xenrt.XRTFailure("Management '%s' missing IP "
                                               "address" % (netname))
            if not ignorestorage:
                if storage and i == "None":
                    raise xenrt.XRTFailure("Storage '%s' missing IP "
                                           "configuration" % (netname))
                if storage and not ip:
                    # Try again after a brief pause
                    xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                           "checking again...")
                    xenrt.sleep(30)
                    ip = self.genParamGet("pif", pif, "IP")
                    if not ip:
                        raise xenrt.XRTFailure("Storage '%s' missing IP "
                                               "address" % (netname))
            if not ignoremanagement and not ignorestorage:
                if (not mgmt and not storage) and i != "None":
                    raise xenrt.XRTFailure("'%s' has IP configuration "
                                           "but is not management or "
                                           "storage" % (netname))
            # TODO: check the IP addresses in dom0 are on the right
            # devices
                
        # Check VLANs
        for p in physList:
            network, nicList, mgmt, storage, vms, friendlynetname, jumbo, vlanList, bondMode = p
            for v in vlanList:
                vnetwork, vmgmt, vstorage, vvms, vfriendlynetname = v
                vid, subnet, netmask = self.getVLAN(vnetwork)
                xenrt.TEC().logverbose("Checking VLAN %s on %s (%s)" %
                                       (vnetwork, network, str(nicList)))
                netname = "VLAN %s on %s %s" % (vnetwork,
                                                network,
                                                string.join(map(str, nicList)))
                # Ensure we only have one network for this bond
                n = self.minimalList("network-list",
                                     "uuid",
                                     "name-label=\"%s\"" % (netname))
                if len(n) == 0:
                    raise xenrt.XRTFailure("Could not find network for '%s'"
                                           % (netname))
                if len(n) > 1:
                    raise xenrt.XRTFailure("Found multiple networks for '%s'"
                                           % (netname))
                # Get the PIF for this network on this host
                pifstring = self.genParamGet("network", n[0], "PIF-uuids")
                if pifstring == "":
                    raise xenrt.XRTFailure("Network '%s' has no PIFs" %
                                           (netname))
                npifs = pifstring.split("; ")
                hpifs = self.minimalList("pif-list",
                                         "uuid",
                                         "host-uuid=%s" %
                                         (self.getMyHostUUID()))
                pif = None
                for p in npifs:
                    if p in hpifs:
                        pif = p
                        break
                if not pif:
                    raise xenrt.XRTFailure("Could not find PIF for '%s' on "
                                           "this host" % (netname),
                                           "host %s" % (self.getName()))
                # Check the PIF has the correct VLAN tag
                v = self.genParamGet("pif", pif, "VLAN")
                if v != str(vid):
                    raise xenrt.XRTFailure("VLAN PIF for %s did not have "
                                           "correct VLAN ID" % (netname),
                                           "PIF %s VLAN %u but was '%s'" %
                                           (pif, vid, v))
                # Get the tagged PIF we expect this to connect to
                if len(nicList) == 1:
                    # raw PIF
                    exppif = self.getNICPIF(nicList[0])
                else:
                    # bond
                    lpif = self.getNICPIF(nicList[0])
                    bond = self.genParamGet("pif", lpif, "bond-slave-of")
                    exppif = self.genParamGet("bond", bond, "master")
                # Make sure the VLAN plumbing is correct
                vlanuuid = self.parseListForUUID("vlan-list",
                                                 "tagged-PIF",
                                                 exppif,
                                                 "tag=%u" % (vid))
                if not vlanuuid:
                    raise xenrt.XRTFailure("Could not find VLAN object for "
                                           "'%s'" % (netname))
                upif = self.genParamGet("vlan", vlanuuid, "untagged-PIF")
                if upif != pif:
                    raise xenrt.XRTFailure("VLAN PIF inconsistency for '%s'" %
                                           (netname),
                                           "%s vs %s" % (upif, pif))
                # Check the config in dom0 (need to be plugged)
                if plugtest or \
                        (vmgmt and not ignoremanagement) or \
                        (vstorage and not ignorestorage):
                    if not ((vmgmt and not ignoremanagement) or \
                            (vstorage and not ignorestorage)):
                        # Won't necessarily be plugged
                        cli.execute("pif-plug", "uuid=%s" % (pif))
                    tdevice = self.genParamGet("pif", pif, "device")
                    self.checkVLAN(vid, tdevice)

                # Check management and storage IP configuration
                if vmgmt:
                    if not managementPIF:
                        managementPIF = pif
                    mexp = "true"
                else:
                    mexp = "false"
                if vmgmt or vstorage:
                    IPPIFs.append(pif)
                i = self.genParamGet("pif", pif, "IP-configuration-mode")
                ip = self.genParamGet("pif", pif, "IP")
                if not ignoremanagement:
                    m = self.genParamGet("pif", pif, "management")
                    if m != mexp:
                        if mexp == "true":
                            msg = "Management not enabled"
                        else:
                            msg = "Management enabled"
                        raise xenrt.XRTFailure("%s on '%s'" % (msg, netname))
                    if vmgmt and i == "None":
                        raise xenrt.XRTFailure("Management '%s' missing IP "
                                               "configuration" % (netname))
                    if vmgmt and not ip:
                        # Try again after a brief pause
                        xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                               "checking again...")
                        xenrt.sleep(30)
                        ip = self.genParamGet("pif", pif, "IP")
                        if not ip:
                            raise xenrt.XRTFailure("Management '%s' missing "
                                                   "IP address" % (netname))
                if not ignorestorage:
                    if vstorage and i == "None":
                        raise xenrt.XRTFailure("Storage '%s' missing IP "
                                               "configuration" % (netname))
                    if vstorage and not ip:
                        # Try again after a brief pause
                        xenrt.TEC().logverbose("No IP for PIF, waiting and "
                                               "checking again...")
                        xenrt.sleep(30)
                        ip = self.genParamGet("pif", pif, "IP")
                        if not ip:
                            raise xenrt.XRTFailure("Storage '%s' missing IP "
                                                   "address" % (netname))
                if not ignoremanagement and not ignorestorage:
                    if (not vmgmt and not vstorage) and i != "None":
                        raise xenrt.XRTFailure("'%s' has IP configuration "
                                               "but is not management or "
                                               "storage" % (netname))
                # TODO: check the IP addresses in dom0 are on the right
                # devices
    
    def restartToolstack(self):
        self.execdom0("/opt/xensource/bin/xe-toolstack-restart")
        self.waitForXapiStartup()

    def startXapi(self):
        self.execdom0("service xapi start")
        self.waitForXapiStartup()

    def waitForXapiStartup(self):
        now = xenrt.util.timenow()
        deadline = now + 300
        while True:
            if self.execdom0("test -e /var/run/xapi_startup.cookie", retval="code") == 0:
                xenrt.TEC().logverbose("xapi (re)started succcessfully")
                break
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("xapi did not successfully start/restart")
            xenrt.sleep(15)
    
    def checkVersionSpecific(self):
        if self.execdom0("test -e /etc/xensource/installed-repos/xs:main",
                         retval="code") != 0:
            xenrt.TEC().reason("Host installer did not install XenServer package")
            raise xenrt.XRTFailure("Host installer did not install XenServer package")
        Host.checkVersionSpecific(self)

    def networkReset(self,
                     masterIP=None,
                     device=None,
                     ipMode=None,
                     ipAddr=None,
                     netmask=None,
                     gateway=None,
                     dns=None,
                     exceptionExpected=False,
                     setIP=None):
    
        networkReset = "/opt/xensource/bin/xe-reset-networking"
        args = []
        args.append("%s " % networkReset)
        if masterIP:
            args.append("--master %s" % masterIP)
        if device:
            args.append("--device %s" % device)  
        if ipMode:
            args.append("--mode %s" % ipMode)
            if ipMode == "static":
                args.append("--ip %s" % ipAddr)
                args.append("--netmask %s" % netmask)
                if gateway:
                    args.append("--gateway %s" % gateway)
                if dns:
                    args.append("--dns %s" % dns)
        command = " ".join(args)
        self.execdom0("touch /tmp/fist_network_reset_no_warning",timeout=300)
        if exceptionExpected:
            self.execdom0("%s" % command,timeout=120)
        else:
            self.execdom0("nohup %s > f.out 2> f.err < /dev/null &" % command,timeout=120)
        xenrt.sleep(5*60)
        if setIP:
            self.setIP(setIP)
        self.waitForXapi(3600, desc="xapi startup after network reset")
        self.waitForEnabled(3600)

    def storageLinkTailor(self):
        # We don't use the gateway in Boston so no need to drop in replacement certs etc
        pass

    def enableCC(self, reboot=True):
        self.execdom0("sed -i 's/vmlinuz\S*/& xen_netback.netback_max_rx_protocol=0/g' /boot/extlinux.conf")
        MNRHost.enableCC(self, reboot)

    def disableCC(self, reboot=True):
        self.execdom0("sed -i 's/xen_netback.netback_max_rx_protocol=0//g' /boot/extlinux.conf")
        MNRHost.disableCC(self, reboot)

    def tailorForCloudStack(self, isBasic=False):
        # Set the Linux templates with PV args to autoinstall

        if isBasic and isinstance(self, xenrt.lib.xenserver.TampaHost) and self.execdom0("test -e /proc/sys/net/bridge", retval="code") == 0:
            self.execdom0("echo 1 > /proc/sys/net/bridge/bridge-nf-call-iptables")
            self.execdom0("echo 1 > /proc/sys/net/bridge/bridge-nf-call-arptables")
            self.execdom0("sed -i '/net.bridge.bridge-nf-call-iptables/d' /etc/sysctl.conf")
            self.execdom0("sed -i '/net.bridge.bridge-nf-call-arptables/d' /etc/sysctl.conf")
            self.execdom0("echo 'net.bridge.bridge-nf-call-iptables = 1' >> /etc/sysctl.conf")
            self.execdom0("echo 'net.bridge.bridge-nf-call-arptables = 1' >> /etc/sysctl.conf")

        myip = "xenrt-controller.xenrt"

        args = {}
        args["Debian Wheezy 7.0 (64-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip
        args["Debian Wheezy 7.0 (32-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip
        args["Debian Squeeze 6.0 (32-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip
        args["Debian Squeeze 6.0 (64-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip

        args["Ubuntu Lucid Lynx 10.04 (32-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip
        args["Ubuntu Lucid Lynx 10.04 (64-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip
        args["Ubuntu Precise Pangolin 12.04 (32-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip
        args["Ubuntu Precise Pangolin 12.04 (64-bit)"] = "auto=true priority=critical console-keymaps-at/keymap=us preseed/locale=en_US auto-install/enable=true netcfg/choose_interface=eth0 url=http://%s/xenrt/guestfile/preseed" % myip

        args["Red Hat Enterprise Linux 4.5 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 4.6 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 4.7 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 4.8 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 5 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 5 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 6 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 6 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 6.0 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Red Hat Enterprise Linux 6.0 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip

        args["CentOS 4.5 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 4.6 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 4.7 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 4.8 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 5 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 5 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 6 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 6 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 6.0 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["CentOS 6.0 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip

        args["Oracle Enterprise Linux 5 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Oracle Enterprise Linux 5 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Oracle Enterprise Linux 6 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Oracle Enterprise Linux 6 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Oracle Enterprise Linux 6.0 (32-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        args["Oracle Enterprise Linux 6.0 (64-bit)"] = "graphical utf8 ks=http://%s/xenrt/guestfile/kickstart" % myip
        
        args["SUSE Linux Enterprise Server 10 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP1 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP1 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP2 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP2 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP3 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP3 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP4 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 10 SP4 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip

        args["SUSE Linux Enterprise Server 11 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 11 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 11 SP1 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 11 SP1 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 11 SP2 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 11 SP2 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 11 SP3 (32-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip
        args["SUSE Linux Enterprise Server 11 SP3 (64-bit)"] = "console=ttyS0 xencons=ttyS autoyast=http://%s/xenrt/guestfile/kickstart showopts netdevice=eth0 netsetup=dhcp" % myip


        for a in args.keys():
            uuids = self.minimalList("template-list", args="name-label=\"%s\"" % a)
            if len(uuids) == 0:
                xenrt.TEC().logverbose("Warning - could not find template for %s" % a)
                continue
            self.genParamSet("template", uuids[0], "PV-args", args[a])

        if xenrt.TEC().lookup("WORKAROUND_XOP589", False, boolean=True):
            xenrt.TEC().warning("Using XOP-589 workaround")
            for t in ["Debian Wheezy 7 (32-bit)", "Debian Wheezy 7 (64-bit)"]:
                uuids = self.minimalList("template-list", args="name-label=\"%s\"" % t)
                for u in uuids:
                    self.genParamSet("template", u, "name-label", t.replace("7", "7.0"))

#############################################################################
class BostonXCPHost(BostonHost):
  
    def license(self, sku="XE Enterprise", edition=None, expirein=None, v6server=None, activateFree=True, applyEdition=True):
        xenrt.TEC().logverbose("No license required for XCP Host")

    def checkVersionSpecific(self):
        if self.execdom0("test -e /etc/xensource/installed-repos/xcp:main",
                         retval="code") != 0:
            xenrt.TEC().reason("Host installer did not install XCP package")
            raise xenrt.XRTFailure("Host installer did not install XCP package")
        if self.execdom0("test -e /etc/xensource/installed-repos/xs:main",
                         retval="code") == 0:
            xenrt.TEC().reason("Host installer unexpectedly installed xs:main package")
            raise xenrt.XRTFailure("Host installer unexpectedly installed xs:main package")


#############################################################################
class TampaHost(BostonHost):

    NETWORKLOCK_UNLOCKED = "unlocked"
    NETWORKLOCK_DISABLED = "disabled"

    # Dom0 Pinning policy - aligned with /etc/init.d/tune-vcpus
    DOM0_VCPU_PINNED = 'pin'
    DOM0_VCPU_NOT_PINNED = 'nopin'
    DOM0_VCPU_DYNAMIC_PINNING = 'detectpin'

    # Dom0 number of vCPUs - aligned with /etc/init.d/tune-vcpus
    DOM0_MIN_VCPUS = 'min'
    DOM0_MAX_VCPUS = 'max'
    DOM0_DYNAMIC_VCPUS = 'dynamic'

    # Dom0 vCPU policy keys - aligned with /var/lib/xen/tune-vcpus-policy
    POLICY_PIN = 'POLICY_PIN'
    POLICY_DYN = 'POLICY_DYN'

    # Dom0 vCPU policy arguments - aligned with /etc/sysconfig/tune-vcpus
    SAMPLING_PERIOD = 'SAMPLING_PERIOD'
    VM_START_TAIL = 'VM_START_TAIL'
    VM_START_NR_THRESHOLD = 'VM_START_NR_THRESHOLD'
    MAX_NR_DOMAIN0_VCPUS = 'MAX_NR_DOMAIN0_VCPUS'
    DOM0_VCPUS_MIN_IDLE = 'DOM0_VCPUS_MIN_IDLE'
    DOM0_VCPUS_MAX_IDLE = 'DOM0_VCPUS_MAX_IDLE'
    DOM0_VCPUS_STEP = 'DOM0_VCPUS_STEP'

    def postInstall(self):
        MNRHost.postInstall(self)
        if xenrt.TEC().lookup("OPTION_XENOPSD_WORKERS", None):
            self.setXapiWorkerThreadPolicy(workerPoolSize = int(xenrt.TEC().lookup("OPTION_XENOPSD_WORKERS")))
            

    def checkNetworkInterfaceConfig(self, name, proto, ip, netmask, gateway):
        # The Linux Bridge config files aren't present in Tampa, so do the runtime check
        return self.checkNetworkInterfaceConfigRuntime(name, proto, ip, netmask, gateway)
        
    def guestFactory(self):
        return xenrt.lib.xenserver.guest.TampaGuest
        
    def setNetworkLockingMode(self, networkUuid, lockingMode):
        """Sets the network locking mode. Can take values: NETWORKLOCK_UNLOCKED, NETWORKLOCK_DISABLED"""
        
        self.getCLIInstance().execute("network-param-set uuid=%s default-locking-mode=%s" % (networkUuid, lockingMode))
        
    def getNetworkLockingMode(self, networkUuid):
        """Gets the network locking mode. This can only be done if there are no VIFs plugged"""
    
        return self.getCLIInstance().execute("network-param-get uuid=%s param-name=default-locking-mode" % (networkUuid)).strip()
        
    def migrateVDI(self, vdi, sr_uuid):
        self.getCLIInstance().execute("vdi-pool-migrate uuid=%s sr-uuid=%s" % (vdi, sr_uuid))
        return

    def setDom0vCPUPolicy(self, pinning=DOM0_VCPU_DYNAMIC_PINNING, numberOfvCPUs=DOM0_MIN_VCPUS, policyArguments={}):
        if pinning != self.DOM0_VCPU_PINNED and pinning != self.DOM0_VCPU_NOT_PINNED and pinning != self.DOM0_VCPU_DYNAMIC_PINNING:
            raise xenrt.XRTError('Invalid Dom0 pinning policy: %s' % (pinning))
        if numberOfvCPUs != self.DOM0_MIN_VCPUS and numberOfvCPUs != self.DOM0_MAX_VCPUS and numberOfvCPUs != self.DOM0_DYNAMIC_VCPUS:
            raise xenrt.XRTError('Invalid Dom0 number of vCPU policy: %s' % (numberOfvCPUs))

        (tuneVCPUsConfig, policyParams) = self.getDom0vCPUPolicy()
        writePolicy = False
        writePolicyParams = False
        reboot = False

        if tuneVCPUsConfig[self.POLICY_DYN] != numberOfvCPUs:
            writePolicy = True
            reboot = True
        if tuneVCPUsConfig[self.POLICY_PIN] != pinning:
            writePolicy = True
        for (key, value) in policyArguments.iteritems():
            if policyParams[key] != value:
                writePolicyParams = True
                policyParams[key] = value

        if writePolicy:
            self.execdom0('service tune-vcpus stop')
            self.execdom0('service tune-vcpus start %s %s' % (pinning, numberOfvCPUs))

        if writePolicyParams:
            self.execdom0('echo "%s" > /etc/sysconfig/tune-vcpus' % (xenrt.getBasicConfigFileString(policyParams)))

        if reboot:
            self.reboot()
 
    def getDom0vCPUPolicy(self):
        policyParams = {self.SAMPLING_PERIOD: 20,
                        self.VM_START_TAIL: 60,
                        self.VM_START_NR_THRESHOLD: 5,
                        self.MAX_NR_DOMAIN0_VCPUS: 8,
                        self.DOM0_VCPUS_MIN_IDLE: 20,
                        self.DOM0_VCPUS_MAX_IDLE: 40,
                        self.DOM0_VCPUS_STEP: 1}
        tuneVCPUsParamsConf = self.execdom0('cat /etc/sysconfig/tune-vcpus')
        tuneVCPUsParamsConfig = xenrt.parseBasicConfigFileString(tuneVCPUsParamsConf)
        for (key, value) in tuneVCPUsParamsConfig.iteritems():
            policyParams[key] = int(value)

        tuneVCPUsConf = self.execdom0('cat /var/lib/xen/tune-vcpus-policy')
        tuneVCPUsConfig = xenrt.parseBasicConfigFileString(tuneVCPUsConf)
        return (tuneVCPUsConfig, policyParams)
        
    def setXapiWorkerThreadPolicy(self, workerPoolSize=4):
        xenopsdConf = self.execdom0('cat /etc/xenopsd.conf')
        xenopsConfig = xenrt.parseBasicConfigFileString(xenopsdConf)

        currentPoolSize = 4
        if xenopsConfig.has_key('worker-pool-size'):
            currentPoolSize = int(xenopsConfig['worker-pool-size'])

        xenrt.TEC().logverbose("Current worker-pool-size: %d" % (currentPoolSize))
        if currentPoolSize != workerPoolSize:
            xenopsConfig['worker-pool-size'] = '%d' % (workerPoolSize)
            self.execdom0('echo "%s" > /etc/xenopsd.conf' % (xenrt.getBasicConfigFileString(xenopsConfig)))
            self.execdom0('service xenopsd restart')

    def getVcpuInfoByDomId(self):
        command = 'xl vcpu-list'
        vcpuData = self.execdom0(command).splitlines()
        vcpuInfo = {}
        for line in vcpuData[1:]:
            line = line.replace('any cpu', 'any-cpu')

            fields = line.split()
            if len(fields) != 7:
                xenrt.TEC().warning("Invalid data from %s: %s" % (command, line))
            else:
                domId = int(fields[1])
                if vcpuInfo.has_key(domId):
                    if vcpuInfo[domId]['name'] != fields[0]:
                        raise xenrt.XRTFailure("Different domain names reported for Domain-%d.  Expected: %s, Actual: %s" % (domId, vcpuInfo[domId]['name'], fields[0]))
                else:
                    vcpuInfo[domId] = { 'name': fields[0], 'cpus': [], 'vcpus': 0, 'vcpusonline': 0, 'vcpuspinned': 0 }

                vcpuInfo[domId]['vcpus'] += 1

                # Check CPU
                if fields[3].isdigit():
                    vcpuInfo[domId]['vcpusonline'] += 1 
                    cpu = int(fields[3])
                    cpuAffinity = fields[6]
                    if cpuAffinity.isdigit():
                        cpuAffinity = int(cpuAffinity)
                        if cpu != cpuAffinity:
                            raise xenrt.XRTFailure("CPU [%d] does not match affinity [%d]" % (cpu, cpuAffinity))
                        vcpuInfo[domId]['vcpuspinned'] += 1
                    vcpuInfo[domId]['cpus'].append(cpu)
                else:
                    # This VCPU could still be pinned even if offline
                    cpuAffinity = fields[6]
                    if cpuAffinity.isdigit():
                        vcpuInfo[domId]['vcpuspinned'] += 1
   
        return vcpuInfo

    def getCpuUsage(self):
        # Returns how many VCPUs are assigned to each CPU core.
        # Returns a list where the index into the list coresponds to the CPU ID
        vcpuData = self.getVcpuInfoByDomId()
        cpuusage = map(lambda x:vcpuData[x]['cpus'], vcpuData.keys())
        combinedList = []
        for lst in cpuusage:
            combinedList += lst

        cpuUsageList = [] 
        for i in range(self.getCPUCores()):
            cpuUsageList.append(combinedList.count(i))

        return cpuUsageList

    def getHBAAdapterList(self):
        """Retrives the list of fibre channel adapters configured on the host."""
        # Retrieves the number of fibre channel adapters.
        deviceString = self.execdom0("systool -c fc_host -A Device | grep -v Class ; exit 0").strip()
        if not deviceString or re.search("Error opening class", deviceString):
            raise xenrt.XRTError("There are no fibre channel host bus adapters installed on the host.")
        else:
            deviceList = []
            deviceString = deviceString.replace('\"','')
            lines = deviceString.splitlines()
            lines = filter(lambda x:len(x.split('=')) == 2, lines)
            for line in lines:
                deviceList.append(line.split('=')[1].strip())
            xenrt.TEC().logverbose("There are %d %s fibre channel host bus adapters found." %
                                    (len(deviceList), deviceList))
            return deviceList

    def getFCWWPNInfo(self):
        """Retrieves WWPN of the fibre channel adapters installed on the host."""

        # Obtain the number of fibre channel adapters.
        deviceList = self.getHBAAdapterList()

        # If there are fibre channel adapters in the host, form a dictionary to return.
        deviceDict = {}
        for device in deviceList:
            # Obtain system device information [wwpn] for each fc adapters.
            deviceInfoString = self.execdom0("systool -c fc_host -A port_name -d %s | grep port_name; exit 0" % device).strip()
            if not deviceInfoString or re.search("Error opening class", deviceInfoString):
                raise xenrt.XRTError("The requested command to obtain wwpn returned an empty value.")
            else:
                deviceInfoString = deviceInfoString.replace('\"','')
                lines = deviceInfoString.splitlines()
                lines = filter(lambda x:len(x.split('=')) == 2, lines)
                for line in lines:
                    (key, value) = line.split('=')
                    key = ("%s-%s") % (device, key.strip())
                    value = value.strip()
                    value = value[2:]
                    value = [''.join(t) for t in zip(value[::2], value[1::2])]
                    value = ':'.join(value)
                    deviceDict[key.strip()] = value.strip()

            xenrt.TEC().logverbose("The system device wwpn information are %s " % deviceDict)
        return deviceDict

    def scanScsiBus(self, timeout=30):
        """Scanning SCSI subsystem for new devices"""

        # Scan the scsi subsystem for new devices.
        self.execdom0("rescan-scsi-bus.sh > rescan-scsi-bus.dat 2>&1 < /dev/null &", retval="code")

        # Wait for some time to complete the scanning of devices.
        startTime = xenrt.util.timenow()
        while True:
            if (xenrt.util.timenow() - startTime) > timeout * 60:
                raise xenrt.XRTFailure("Scanning SCSI subsystem for new devices took more than %u minutes" %
                                                                                                        timeout)
            if self.execdom0("ps -efl | grep [r]escan-scsi-bus.sh",retval="code") > 0:
                xenrt.TEC().logverbose("Scanning SCSI subsystem for new devices took %u minutes" %
                                                                ((xenrt.util.timenow() - startTime)/60))
                break

            xenrt.sleep(30) # 30 seconds.

    def scanFibreChannelBus(self):
        """Scans the fibre channel bus for luns."""

        # Obtain the number of fibre channel adapters.
        #deviceList = self.getHBAAdapterList()

        # Scan each fibre channel adapter for luns.
        #for device in deviceList:
        #    self.execdom0("echo '- - -' > /sys/class/scsi_host/%s/scan; exit 0" % device)

        # Alternatively using storage manager code to refresh the adapters.
        self.execdom0("%s/remote/scanadapters.py" % (xenrt.TEC().lookup("REMOTE_SCRIPTDIR")), timeout=7200)
        
    def getAlternativesDir(self):
        return "/opt/xensource/alternatives"
        
    def getXenGuestLocation(self):
        return "/opt/xensource/libexec/xenguest"
        
    def getQemuDMWrapper(self):
        return "/opt/xensource/libexec/qemu-dm-wrapper"

    
    def validLicenses(self, xenserverOnly=False):
        """
        Get a license object which contains the details of a license settings
        for a given SKU
        sku: XenServerLicenseSKU member
        """
        factory = XenServerLicenseFactory()
        if xenserverOnly:
            return factory.xenserverOnlyLicenses(self)
        return factory.allLicenses(self)


#############################################################################
class TampaXCPHost(TampaHost):

    def license(self, sku="XE Enterprise", edition=None, expirein=None, v6server=None, activateFree=True, applyEdition=True):
        xenrt.TEC().logverbose("No license required for XCP Host")

    def checkVersionSpecific(self):
        if self.execdom0("test -e /etc/xensource/installed-repos/xcp:main",
                         retval="code") != 0:
            xenrt.TEC().reason("Host installer did not install XCP package")
            raise xenrt.XRTFailure("Host installer did not install XCP package")
        if self.execdom0("test -e /etc/xensource/installed-repos/xs:main",
                         retval="code") == 0:
            xenrt.TEC().reason("Host installer unexpectedly installed xs:main package")
            raise xenrt.XRTFailure("Host installer unexpectedly installed xs:main package")

#############################################################################
class ClearwaterHost(TampaHost):
    # Dom0 Exclusive Pinning policy - aligned with /usr/lib/xen/bin/host-cpu-tune
    DOM0_VCPU_PINNED = 'xpin'
    DOM0_VCPU_NOT_PINNED = 'nopin'
    
    #This is a temp license function once clearwater and trunk will be in sync this will become "license" funtion
    def license(self, edition = "per-socket", v6server = None, sku=None):

        cli = self.getCLIInstance()
        args = []

        if sku:
            edition = sku

        if edition == "per-socket" or edition == "xendesktop":

            licensed = True
        else:
            
            licensed = False
 
        args.append("host-uuid=%s" % (self.getMyHostUUID()))
        args.append("edition=%s" % (edition))
  
        if v6server:
            args.append("license-server-address=%s" % (v6server.getAddress()))
            args.append("license-server-port=%s" % (v6server.getPort()))
        else:
            (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_LICENSE_SERVER").split(":")
            args.append("license-server-address=%s" % (addr))
            args.append("license-server-port=%s" % (port))

        cli.execute("host-apply-edition", string.join(args))

        self.checkHostLicenseState(edition , licensed, checkFeatures=False)
  
    def checkHostLicenseState(self, edition, licensed = False, checkFeatures=True):

        details = self.getLicenseDetails()

        if not details.has_key("edition"):
            raise xenrt.XRTFailure("Host %s doesnt have any license edition" % (self.getName()))
        if not (edition == details["edition"]):
            raise xenrt.XRTFailure("Host %s is not licensed with %s. Is has got edition %s" % (self.getName() , edition , details["edition"]))

        if checkFeatures:

            if not details.has_key("restrict_hotfix_apply"):
                raise xenrt.XRTFailure("Host %s does not have restrict_hotfix_apply" % (self.getName()))
    
            if edition == "free" or licensed == False:
                if details["restrict_hotfix_apply"] == "false":
                    raise xenrt.XRTFailure("Hotfix can be applied through Xencenter when host %s is not licensed" % (self.getName()))
            elif licensed == True:
                if details["restrict_hotfix_apply"] == "True":
                    raise xenrt.XRTFailure("Hotfix cannot be applied through Xencenter when host %s is licensed" % (self.getName()))
                
    def checkSkuMarketingName(self):

        details = self.getLicenseDetails()
         
        if not details.has_key("edition"):
            raise xenrt.XRTFailure("Host %s doesnt have any license edition" % (self.getName()))
        
        if not details.has_key("restrict_hotfix_apply"):
            raise xenrt.XRTFailure("Host %s does not have restrict_hotfix_apply" % (self.getName()))
         
        edition = details["edition"]
        skuname = details["sku_marketing_name"]
        hotfixstatus = details["restrict_hotfix_apply"]        
        
        if hotfixstatus == "True" and edition == "per-socket" :
        
            if not skuname == "Citrix XenServer":
                raise xenrt.XRTFailure("Sku_Marketing_Name %s doesnt correspond to the Expired Host edition %s" % (skuname,edition))
        
        elif not ((edition == "free" and skuname == "Citrix XenServer") \
                            or (edition == "per-socket" and skuname == "Citrix XenServer Licensed") \
                            or (edition=="xendesktop" and skuname == "Citrix XenServer for XenDesktop")) :
            raise xenrt.XRTFailure("Sku_Marketing_Name %s doesnt matches with the edition %s" % (skuname,edition))            

    def installv6dRPM(self):
 
        filename = "v6d.rpm"
        v6d = xenrt.TEC().getFile("binary-packages/RPMS/domain0/RPMS/i686/v6d-0-*.rpm") 
 
        try:
            xenrt.checkFileExists(v6d)
        except:
            raise xenrt.XRTError("v6d rpm file is not present in the build")

        v6rpmPath = "/tmp/%s" % (filename)

        #Upload the contents of iso onto a http server
        sh = self.host.sftpClient()
        try:
            sh.copyTo(v6d,v6rpmPath)
        finally:
            sh.close()

        self.execdom0("rpm --force -Uvh %s" % (v6rpmPath))
        
        self.execdom0("service v6d restart")

    def getDefaultAdditionalCDList(self):
        """Return a list of additional CDs to be installed.
        The list is a string of comma-separated ISO names or None if
        there are no additional CDs. The result is determined
        by the value of CARBON_EXTRA_CDS - if this is not set or set to the
        value of "DEFAULT" then the product default is used. If this is set
        it is used as-is."""
        ecds = self.lookup("CARBON_EXTRA_CDS", None)
        if not ecds or ecds == "DEFAULT":
            ecds = self.lookup("DEFAULT_EXTRA_CDS", None)
        if ecds == "NONE":
            ecds = None
        return ecds
    
    def guestFactory(self):
        return xenrt.lib.xenserver.guest.ClearwaterGuest

    def setDom0PinningPolicy(self, numberOfvCPUs, pinning):
        if pinning:
            pinningPolicy = self.DOM0_VCPU_PINNED 
        else:
            pinningPolicy = self.DOM0_VCPU_NOT_PINNED
        ret = self.execdom0('%s set %s %s' % (self._findXenBinary('host-cpu-tune'), numberOfvCPUs, pinningPolicy))
        
        if "ERROR" in ret:
            raise xenrt.XRTFailure(ret)
        
        self.reboot()

    def getDom0PinningPolicy(self):
        vcpuPinningData = {}
        output = self.execdom0('%s show' % self._findXenBinary('host-cpu-tune'))
        output = output.split(':')[1].strip().split(', ')
        vcpuPinningData['dom0vCPUs'] = output[0]
        if re.search('exclusively pinned', output[1]):
            vcpuPinningData['pinning'] = True
        else:
            vcpuPinningData['pinning'] = False
        return vcpuPinningData

    def getVcpuInfoByDomId(self):
        command = 'xl vcpu-list'
        vcpuData = self.execdom0(command).splitlines()
        vcpuInfo = {}
        for line in vcpuData[1:]:
            line = line.replace('any cpu', 'any-cpu')

            fields = line.split()
            if len(fields) < 7:
                xenrt.TEC().warning("Invalid data from %s: %s" % (command, line))
            else:
                domId = int(fields[1])
                if vcpuInfo.has_key(domId):
                    if vcpuInfo[domId]['name'] != fields[0]:
                        raise xenrt.XRTFailure("Different domain names reported for Domain-%d.  Expected: %s, Actual: %s" % (domId, vcpuInfo[domId]['name'], fields[0]))
                else:
                    vcpuInfo[domId] = { 'name': fields[0], 'cpus': [], 'vcpus': 0, 'vcpusonline': 0, 'vcpuspinned': 0 , 'cpuaffinity': []}

                vcpuInfo[domId]['vcpus'] += 1

                # Check CPU
                if fields[3].isdigit():
                    vcpuInfo[domId]['vcpusonline'] += 1 
                    cpu = int(fields[3])
                    cpuAffinity = fields[6]
                    if cpuAffinity.isdigit():
                        cpuAffinity = int(cpuAffinity)
                        if cpu != cpuAffinity:
                            raise xenrt.XRTFailure("CPU [%d] does not match affinity [%d]" % (cpu, cpuAffinity))
                        if cpuAffinity not in vcpuInfo[domId]['cpuaffinity']:
                            vcpuInfo[domId]['cpuaffinity'].append(cpuAffinity)
                        vcpuInfo[domId]['vcpuspinned'] += 1
                    elif not re.search('any-cpu',cpuAffinity) and re.search('-', cpuAffinity):
                        affinityRange = map(int, cpuAffinity.split('-'))
                        pcpu = affinityRange[0]
                        pcpuUpperLimit = affinityRange[1]
                        while pcpu <= pcpuUpperLimit:
                            if pcpu not in vcpuInfo[domId]['cpuaffinity']:
                                vcpuInfo[domId]['cpuaffinity'].append(pcpu)
                            pcpu += 1   
                        if cpu not in vcpuInfo[domId]['cpuaffinity']:
                            raise xenrt.XRTFailure("CPU [%d] does not match affinity [%d]" % (cpu, cpuAffinity))
                    vcpuInfo[domId]['cpus'].append(cpu) 
        return vcpuInfo

    def restoreOldInstallation(self):
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
                                     
        comport = str(int(serport) + 1)
        xen_extra_args = self.lookup("XEN_EXTRA_ARGS", None)
        xen_extra_args_user = self.lookup("XEN_EXTRA_ARGS_USER", None)
        if xen_extra_args_user:
            xen_extra_args_user = string.replace(xen_extra_args_user, ",", " ")
        dom0_extra_args = self.lookup("DOM0_EXTRA_ARGS", None)
        dom0_extra_args_user = self.lookup("DOM0_EXTRA_ARGS_USER", None)
        pxe = xenrt.PXEBoot()
        xenrt.TEC().logverbose("Using ISO %s" % (self.cd))
        mount = xenrt.MountISO(self.cd)
        mountpoint = mount.getMount()
        pidir = xenrt.WebDirectory()
        packdir = xenrt.WebDirectory()
        pxe.copyIn("%s/boot/*" % (mountpoint))
        pxe.copyIn("%s/install.img" % (mountpoint))
        
        workdir = xenrt.TEC().getWorkdir()
        # Create an NFS directory for the installer to signal completion
        nfsdir = xenrt.NFSDirectory()

        ansfile = "%s/%s-restore.xml" % (workdir, self.getName())
        ans = file(ansfile, "w")
        furl = pidir.getURL("install-failed-script-%s" % (self.getName()))

        anstext = """<?xml version="1.0"?>
<restore>
<backup-disk>%s</backup-disk>
<install-failed-script>%s</install-failed-script>
</restore>
""" % (self.getInstallDisk(ccissIfAvailable=self.USE_CCISS, legacySATA=(not self.isCentOS7Dom0())), furl)
        ans.write(anstext)
        ans.close()
        packdir.copyIn(ansfile)

        # Create a script to run on install failure (on builds that
        # support this)
        fifile = "%s/install-failed-script-%s" % (workdir,self.getName())
        fi = file(fifile, "w")
        fitext = """#!/bin/bash

if [ "$1" = "0" ]; then
    
    echo "Successful install, not running fail commands."
    # Signal XenRT that we've finished
    mkdir /tmp/xenrttmpmount
    mount -t nfs %s /tmp/xenrttmpmount
    touch /tmp/xenrttmpmount/.xenrtsuccess
    umount /tmp/xenrttmpmount
    exit 0
fi

# Signal XenRT that we've failed
mkdir /tmp/xenrttmpmount
mount -t nfs %s /tmp/xenrttmpmount
echo "Failed install" > /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
cat /proc/partitions >> /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
for i in /sys/block/*/device/vendor; do echo $i; cat $i; done >> /tmp/failedinstall
for i in /sys/block/*/device/model; do echo $i; cat $i; done >> /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
if [ -x /opt/xensource/installer/report.py ]; then
  /opt/xensource/installer/report.py file:///tmp/xenrttmpmount
fi
cat /tmp/failedinstall /tmp/install-log > /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount

# Now stop here so we don't boot loop
while true; do
    sleep 30
done
""" % (nfsdir.getMountURL(""), nfsdir.getMountURL(""))
        fi.write(fitext)
        fi.close()
        pidir.copyIn(fifile)
        xenrt.TEC().copyToLogDir(fifile)

        # Set the boot files and options for PXE
        if self.lookup("PXE_NO_SERIAL", False, boolean=True):
            pxe.setSerial(None,None)
        else:
            pxe.setSerial(serport, serbaud)
        if self.lookup("PXE_NO_PROMPT", False, boolean=True):
            pxe.setPrompt("0")
        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")
        pxecfg = pxe.addEntry("carboninstall", default=1, boot="mboot")
        xenfiles = glob.glob("%s/boot/xen*" % (mountpoint))
        xenfiles.extend(glob.glob("%s/boot/xen.gz" % (mountpoint)))
        if len(xenfiles) == 0:
            raise xenrt.XRTError("Could not find a xen* file to boot")
        xenfile = os.path.basename(xenfiles[-1])
        kernelfiles = glob.glob("%s/boot/vmlinuz*" % (mountpoint))
        if len(kernelfiles) == 0:
            raise xenrt.XRTError("Could not find a vmlinuz* file to boot")
        kernelfile = os.path.basename(kernelfiles[-1])
        pxecfg.mbootSetKernel(xenfile)
        pxecfg.mbootSetModule1(kernelfile)
        pxecfg.mbootSetModule2("install.img")
        
        pxecfg.mbootArgsKernelAdd("watchdog")
        pxecfg.mbootArgsKernelAdd("com%s=%s,8n1" % (comport, serbaud))
        pxecfg.mbootArgsKernelAdd("console=com%s,tty" % (comport))
        if isinstance(self, xenrt.lib.xenserver.DundeeHost):
            pxecfg.mbootArgsKernelAdd("dom0_mem=1024M,max:1024M")
        elif isinstance(self, xenrt.lib.xenserver.TampaHost):
            pxecfg.mbootArgsKernelAdd("dom0_mem=752M,max:752M")
        else:
            pxecfg.mbootArgsKernelAdd("dom0_mem=752M")
        pxecfg.mbootArgsKernelAdd("dom0_max_vcpus=2")
        if xen_extra_args:
            pxecfg.mbootArgsKernelAdd(xen_extra_args)
            xenrt.TEC().warning("Using installer extra Xen boot args %s" %
                                (xen_extra_args))
        if xen_extra_args_user:
            pxecfg.mbootArgsKernelAdd(xen_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Xen boot args %s" %
                                (xen_extra_args_user))
        
        pxecfg.mbootArgsModule1Add("root=/dev/ram0")
        if self.special.has_key("dom0 uses hvc") and \
               self.special["dom0 uses hvc"]:
            pxecfg.mbootArgsModule1Add("console=tty0")
            pxecfg.mbootArgsModule1Add("xencons=hvc")
            pxecfg.mbootArgsModule1Add("console=hvc0")
        else:
            pxecfg.mbootArgsModule1Add("console=tty0")
            pxecfg.mbootArgsModule1Add("console=ttyS%s,%sn8" %
                                       (serport, serbaud))
        pxecfg.mbootArgsModule1Add("ramdisk_size=65536")
        pxecfg.mbootArgsModule1Add("install")
        pxecfg.mbootArgsModule1Add("rt_answerfile=%s" % (packdir.getURL("%s-restore.xml" % (self.getName()))))
        pxecfg.mbootArgsModule1Add("output=ttyS0")
        mac = self.lookup("MAC_ADDRESS", None)
        if mac:
            pxecfg.mbootArgsModule1Add("answerfile_device=%s" % (mac))
        if dom0_extra_args:
            pxecfg.mbootArgsModule1Add(dom0_extra_args)
            xenrt.TEC().warning("Using installer extra Dom0 boot args %s" %
                                (dom0_extra_args))
        if dom0_extra_args_user:
            pxecfg.mbootArgsModule1Add(dom0_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Dom0 boot args %s"
                                % (dom0_extra_args_user))

        optionRootMpath = self.lookup("OPTION_ROOT_MPATH", None)
        
        if optionRootMpath != None and len(optionRootMpath) > 0:
            pxecfg.mbootArgsModule1Add("device_mapper_multipath=%s" % optionRootMpath)
        
        # Set up PXE for installer boot
        pxefile = pxe.writeOut(self.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))
        
        mount.unmount()
        if self.lookup("INSTALL_DISABLE_FC", False, boolean=True):
            self.disableAllFCPorts()
        self._softReboot()
        xenrt.TEC().progress("Rebooted host to start installer.")
        
        installTimeout = 1800 + int(self.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0"))
        xenrt.waitForFile("%s/.xenrtsuccess" % (nfsdir.path()),
                                  installTimeout,
                                  desc="Installer boot on !%s" %
                                  (self.getName()))

        self.checkHostInstallReport("%s/.xenrtsuccess" % (nfsdir.path()))
        xenrt.TEC().progress("Restore complete, waiting for host boot.")
        
        # Boot the local disk  - we need to update this before the machine
        # reboots after setting the signal flag.
        pxe.setDefault("local")
        pxe.writeOut(self.machine)
        # Wait for the machine to come up so we can SSH in. The sleep is
        # to avoid trying to SSH to the installer
        xenrt.sleep(30)
        self.waitForSSH(900, desc="Host boot (!%s)" % (self.getName()))

    def isGPUCapable(self):

        vgpuTypeList = self.minimalList("vgpu-type-list")

        if not vgpuTypeList:
            return False

        return True

    def getSupportedVGPUTypes(self):
 
        vgpuType = {}

        if self.isGPUCapable():

            vgpuTypeList = self.minimalList("vgpu-type-list")

            for vgpuTypeUUID in vgpuTypeList:
                vgpuType[self.genParamGet('vgpu-type',vgpuTypeUUID,'model-name')] = vgpuTypeUUID
            
        else:
            xenrt.TEC().logverbose("No VGPU type is supported on this host")
      
        return vgpuType 
    
    def destroyAllvGPUs(self):
        vgpuList = []
        try:
            vgpuList = self.minimalList("vgpu-list")
        except:
            return
        
        for vgpuUUID in vgpuList:
            self.execdom0("xe vgpu-destroy uuid=%s" % vgpuUUID)

    def setDepthFirstAllocationType(self,gpuGroupUUID):

        self.genParamSet("gpu-group",gpuGroupUUID,"allocation-algorithm","depth-first")

    def setBreadthFirstAllocationType(self,gpuGroupUUID):

        self.genParamSet("gpu-group",gpuGroupUUID,"allocation-algorithm","breadth-first")

    def checkRPMInstalled(self, rpm):
        """
        Check if a specific rpm is installed
        @param rpm: the rpm name including or excluding the extension '.rpm'
        @type rpm: string
        @return If the rpm provided is installed already
        @rtype boolean
        """

        #rpm should NOT contain file extn .rpm, so split off any file extension
        fileWithoutExt = os.path.splitext(rpm)[0]
        try:
            data = self.execdom0("rpm -qi %s" % fileWithoutExt)
        except:
            return False

        if "is not installed" in data:
            return False
        else:
            return True

    def installNVIDIAHostDrivers(self, reboot=True,ignoreDistDriver = False):
        rpmDefault="NVIDIA-vgx-xenserver-6.2-331.59.00.i386.rpm"
        inputDir = xenrt.TEC().lookup("INPUTDIR", default=None)
        rel = xenrt.TEC().lookup("RELEASE", default=None)

        getItFromDist = False

        if inputDir and rel:
            branch = inputDir.split("/")[-2]
            build = inputDir.split("/")[-1]
            url = "http://vgpubuilder.uk.xensource.com/%s/%s/vgpuhost.rpm" % (branch,build)
            try:
                self.execdom0("wget --directory-prefix=/tmp %s" % url)
                data=self.execdom0("rpm -qpil /tmp/vgpuhost.rpm")
                m=re.match(r"Name *[^:]*: (\S+)", data)
                rpm = m.group(1)
                self.execdom0("mv /tmp/vgpuhost.rpm /tmp/%s.rpm" % rpm)
                rpm = rpm + '.rpm'
            except Exception, e:
                xenrt.TEC().logverbose("Following error was thrown while trying to get host drivers from vGPU server %s " % str(e))
                if ignoreDistDriver:
                    return False
                getItFromDist = True
                                 
        else:
            getItFromDist = True

        if getItFromDist:
            rpm = xenrt.TEC().lookup("VGPU_HOST_DRIVER_RPM", default=rpmDefault)

            url = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
            hostRPMURL = "%s/vgpudriver/hostdriver/%s" %(url,rpm)
            hostRPM = xenrt.TEC().getFile(hostRPMURL,hostRPMURL)

            try:
                xenrt.checkFileExists(hostRPM)
            except:
                raise xenrt.XRTError("Host RPM not found")

            hostPath = "/tmp/%s" % (rpm)

            sh = self.sftpClient()

            try:
                sh.copyTo(hostRPM,hostPath)
            finally:
                sh.close()

        xenrt.TEC().logverbose("Installing Host driver: %s" % rpm)

        if self.checkRPMInstalled(rpm):
            xenrt.TEC().logverbose("NVIDIA Host driver is already installed")
            return True

        self.execdom0("rpm -ivh /tmp/%s" % (rpm))
        if reboot:
            self.reboot()
 
        return True

    def remainingGpuCapacity(self, groupUUID, vGPUTypeUUID):
        return int(self.execdom0("xe gpu-group-get-remaining-capacity uuid=%s vgpu-type-uuid=%s" %(groupUUID,vGPUTypeUUID)))
        
    def installComplete(self, handle, waitfor=False, upgrade=False): 
    
        MNRHost.installComplete(self, handle, waitfor, upgrade)
        if xenrt.TEC().lookup("OPTION_DOM0_PINNING", False, boolean=True) and self.getCPUCores()>=8:
            xenrt.TEC().comment("Dom0 vcpus are getting exclusively pinned")
            self.setDom0PinningPolicy('4', True)
            vcpuPinningData = self.getDom0PinningPolicy()
            xenrt.TEC().logverbose("Dom0 vCPU count: %s" % vcpuPinningData['dom0vCPUs'])
            xenrt.TEC().logverbose("Dom0 Pinning status: %s" % vcpuPinningData['pinning'])
            if vcpuPinningData['dom0vCPUs']!='4' or not vcpuPinningData['pinning']:
                raise xenrt.XRTFailure("Dom0 vCPU pinning policy not present after reboot")        

        setxen = xenrt.TEC().lookup("SETXENCMDLINE", None) #eg. SETXENCMDLINE=x=a,y=b
        if setxen:
            args=dict(map(lambda a: tuple(a.split("=")), setxen.split(",")))
            self.setXenCmdLine(**args)

        setkernel = xenrt.TEC().lookup("SETKERNELCMDLINE", None) #eg. SETKERNELCMDLINE=x=a,y=b
        if setkernel:
            args=dict(map(lambda a: tuple(a.split("=")), setkernel.split(",")))
            self.setXenCmdLine(set="dom0", **args)

        if setxen or setkernel:
            xenrt.TEC().logverbose("changed boot params; reboot required")
            self.reboot()

        if xenrt.TEC().lookup("FORCE_NON_DEBUG_XEN", None):
            self.assertNotRunningDebugXen()

    def postInstall(self):
        TampaHost.postInstall(self)
        #CP-6193: Verify check for XenRT installation cookie
        if not self.execdom0("cat /root/xenrt-installation-cookie", retval = 'code'):
            if self.execdom0("cat /root/xenrt-installation-cookie").strip() == self.installationCookie :
                xenrt.TEC().logverbose("XenServer gets booted from the right disk as installation cookie is detected as expected.")
            else:
                raise xenrt.XRTFailure("XenServer booted from wrong disk. Installation cookie does not match.")
        else:
            raise xenrt.XRTFailure ("XenRT Insallation cookie file does not exist")

        if xenrt.TEC().lookup("OPTION_ENABLE_GRO", False, boolean=True):
            nics = [0]
            nics.extend(self.listSecondaryNICs())
            for n in nics:
                eth = self.getNIC(n)
                pif = self.getNICPIF(n)
                self.execdom0("ethtool -K %s gro on" % eth)
                self.genParamSet("pif", pif, "other-config:ethtool-gro", "on")

        if xenrt.TEC().lookup("INSTALL_VGPU_DRIVER", False, boolean=True):
            self.installNVIDIAHostDrivers()

    def resetToFreshInstall(self, setupISOs=False):
        self.installationCookie = self.execdom0("cat /root/xenrt-installation-cookie").strip()
        TampaHost.resetToFreshInstall(self, setupISOs)

    def startVifDebug(self, domid):
        try:
            self.execdom0("killall -9 debugfs")
        except:
            pass
        self.execdom0("%s/debugfs %d </dev/null > /tmp/vifdebug.%d.log 2>&1 &" % (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), int(domid), int(domid)))
        

    def stopVifDebug(self, domid):
        try:
            self.execdom0("killall -9 debugfs")
        except:
            pass
        xenrt.TEC().logverbose(self.execdom0("cat /tmp/vifdebug.%d.log" % int(domid)))

    def installNVIDIASupPack(self):

        def getURL():
            baseurl = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
            return "%s/vgpudriver/hostdriver/" % (baseurl)

        defaultSupPack = "NVIDIA-vgx-xenserver-6.5-346.61.x86_64.iso"
        suppack = xenrt.TEC().lookup("VGPU_SUPPACK", default=defaultSupPack)

        if not self.checkRPMInstalled(suppack):
            url = getURL()
            self.installHostSupPacks(url, suppack)

#############################################################################

class CreedenceHost(ClearwaterHost):

    def guestFactory(self):
        return xenrt.lib.xenserver.guest.CreedenceGuest

    def getReadCachingController(self):
        return xenrt.lib.xenserver.readcaching.ReadCachingController(self)

    def enableReadCaching(self, sruuid=None):
        if sruuid:
            srlist = [sruuid]
        else:
            srlist = self.minimalList("sr-list")

        for sr in srlist:
            type = self.genParamGet("sr", sr, "type")
            # Read cache only works for ext and nfs.
            if type == 'nfs' or type == 'ext':
                # When o_direct is not defined, it is on by default.
                if 'o_direct' in self.genParamGet("sr", sr, "other-config"):
                    self.genParamRemove("sr", sr, "other-config", "o_direct")

    def disableReadCaching(self, sruuid=None):
        if sruuid:
            srlist = [sruuid]
        else:
            srlist = self.minimalList("sr-list")

        for sr in srlist:
            type = self.genParamGet("sr", sr, "type")
            # Read cache only works for ext and nfs.
            if type == 'nfs' or type == 'ext':
                oc = self.genParamGet("sr", sr, "other-config")
                # When o_direct is not defined, it is on by default.
                if 'o_direct' not in oc or 'true' not in self.genParamGet("sr", sr, "other-config", "o_direct"):
                    self.genParamSet("sr", sr, "other-config", "true", "o_direct")

    def vSwitchCoverageLog(self):
        self.vswitchAppCtl("coverage/show")

    def license(self, v6server=None, sku="enterprise-per-socket", edition=None):
        """
        In order to keep backwards compatability "sku" arg is called sku
        but really it needs the edition to be passed in
        """
        cli = self.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (self.getMyHostUUID()))

        #WORKAROUND, should be removed once all the branches are in sync
        ed = xenrt.TEC().lookup("EDITION",default=None)
        if ed:
            sku=ed

        if edition:
            sku = edition

        args.append("edition=%s" % sku)
        if v6server:
            args.append("license-server-address=%s" % (v6server.getAddress()))
            args.append("license-server-port=%s" % (v6server.getPort()))
        else:
            if self.special.has_key('v6earlyrelease') and self.special['v6earlyrelease']:
                (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_PREVIEW_LICENSE_SERVER").split(":")
            else:
                (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_LICENSE_SERVER").split(":")
            args.append("license-server-address=%s" % (addr))
            args.append("license-server-port=%s" % (port))

        cli.execute("host-apply-edition", string.join(args))
        self.checkLicenseState(sku)

    def licensedFeatures(self):
        return LicensedFeatureFactory().allFeatures(self)

    def checkLicenseState(self, edition):

        details = self.getLicenseDetails()

        if not details.has_key("edition"):
            raise xenrt.XRTFailure("Host %s doesnt have any license edition" % (self.getName()))
        if not (edition == details["edition"]):
            raise xenrt.XRTFailure("Host %s is not licensed with %s. Is has got edition %s" % (self.getName() , edition , details["edition"]))

        xenrt.TEC().logverbose("Edition is same on host as expected")

    def licenseApply(self, v6server, licenseObj):
        self.license(v6server=v6server, sku=licenseObj.getEdition())

    def createTemplateSR(self):
        if xenrt.TEC().lookup("SHARED_VHD_PATH_NFS", None):
            sr = xenrt.lib.xenserver.NFSStorageRepository(self, "Remote Template Library")
            sr.uuid = TEMPLATE_SR_UUID
            sr.srtype = "nfs"
            sr.content_type="user"
            (server, path) = xenrt.TEC().lookup("SHARED_VHD_PATH_NFS").split(":")
            sr.dconf = {"server": server, "serverpath": path}
            sr.introduce(nosubdir = True)
            return sr
        else:
            raise xenrt.XRTError("No NFS path defined")

    def installContainerPack(self):
        with xenrt.GEC().getLock("CONTAINER_PACK_INSTALL_%s" % self.getName()):
            if self.execdom0("test -e /etc/xensource/installed-repos/xs:xscontainer", retval="code") == 0:
                return

            f = xenrt.TEC().getFile(
                "xe-phase-2/xscontainer-6*.iso",
                "xe-phase-2/xscontainer-7*.iso",
                "${CREAM_BUILD_DIR}xe-phase-2/xscontainer-6.5.0-*.iso")
        
            if not f:
                raise xenrt.XRTError("Container supplemental pack not found")

            # Copy ISO from the controller to host in test
            sh = self.sftpClient()
            try:
                sh.copyTo(f,"/tmp/xscontainer.iso")
            finally:
                sh.close()

            self.execdom0("xe-install-supplemental-pack /tmp/xscontainer.iso")

    def __exectuteAccessCommand(self, uuid, accessCommand):
        if not uuid:
            raise xenrt.XRTFailure("No PGPU uuid given")

        cli = self.getCLIInstance()
        args = []

        args.append("uuid=%s" % uuid)
        cli.execute(accessCommand, string.join(args))

    def blockDom0AccessToOnboardPGPU(self, gpuuuid):
        self.__exectuteAccessCommand(gpuuuid, "pgpu-disable-dom0-access")

    def unblockDom0AccessToOnboardPGPU(self, gpuuuid):
        self.__exectuteAccessCommand(gpuuuid, "pgpu-enable-dom0-access")

    def disableHostDisplay(self):
        self.__exectuteAccessCommand(self.uuid, "host-disable-display")

    def enableHostDisplay(self):
        self.__exectuteAccessCommand(self.uuid, "host-enable-display")

#############################################################################
class DundeeHost(CreedenceHost):
    USE_CCISS = False
    SNMPCONF = "/etc/snmp/snmpd.xs.conf"
    INITRD_REBUILD_SCRIPT = "new-kernel-pkg"
    SOURCE_ISO_FILES = {'source.iso': 'xe-phase-3'}

    def __init__(self, machine, productVersion="Dundee", productType="xenserver"):
        CreedenceHost.__init__(self,
                                machine,
                                productVersion=productVersion,
                                productType=productType)

        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTGro)
        self.registerJobTest(xenrt.lib.xenserver.jobtests.JTDeadLetter)

        self.installer = None
        self.melioHelper = None
        self.haPath = None

    def populateSubclass(self, x):
        CreedenceHost.populateSubclass(self, x)
        x.melioHelper = self.melioHelper
    
    def isCentOS7Dom0(self):
        return True

    def getTestHotfix(self, hotfixNumber):
        return xenrt.TEC().getFile("xe-phase-1/test-hotfix-%u-*.unsigned" % hotfixNumber)

    def guestFactory(self):
        return xenrt.lib.xenserver.guest.DundeeGuest

    def postInstall(self):
        CreedenceHost.postInstall(self)

        # check there are no failed first boot scripts
        self._checkForFailedFirstBootScripts()
        self.execdom0("chmod +x /etc/rc.d/rc.local")
        if xenrt.TEC().lookup("INSTALL_MELIO", False, boolean=True):
            self.installMelio()
        
    def _checkForFailedFirstBootScripts(self):
        for f in self.execdom0("(cd /etc/firstboot.d/state && ls)").strip().splitlines():
            msg = self.execdom0("cat /etc/firstboot.d/state/%s" % f).strip()
            if not "success" in msg:
                self.execdom0("cat /etc/firstboot.d/log/%s.log" % f)
                # Is this a known issue?
                m = re.match("(\d+)-.*", f)
                if m:
                    known = xenrt.TEC().lookup("FBKNOWN_%s" % m.group(1), None)
                    if known and xenrt.jiralink.getJiraLink().isIssueOpen(known):
                        xenrt.TEC().warning("Found known firstboot issue %s in %s" % (known, f))
                        return

                raise xenrt.XRTFailure("firstboot.d %s failed" % f)

    def getSCSIID(self, device):
        return self.execdom0("%s -g --device /dev/%s" % (self.scsiIdPath(), device)).strip()
            
    def getAlternativesDir(self):
        return "/usr/lib/xapi/alternatives"
        
    def getXenGuestLocation(self):
        return self._findXenBinary("xenguest")
        
    def getQemuDMWrapper(self):
        return "/usr/libexec/xenopsd/qemu-dm-wrapper"

    def getBridgeInterfaces(self, bridge):
        """Return a list of interfaces on the bridge, or None if that bridge
        does not exist."""
        # Get network backend
        backend=self.execdom0('cat /etc/xensource/network.conf').strip()
        if not re.search('bridge', backend, re.I):
            try:
                data = self.execdom0('ovs-vsctl list-ports %s' %
                                    bridge)
                ifs = string.split(data)
            except:
                # If we pass in a network name rather than a bridge name this will fail.
                # This is fine, because the calling function will fall through to another method
                return None
        else:
            ifs=CreedenceHost.getBridgeInterfaces(self, bridge)
        return ifs

    def getInstallNetwork(self):
        return getattr(self, "installnetwork", None)
        
    def snmpdIsEnabled(self):
        return "enabled" in self.execdom0("service snmpd status | cat")
            
    def disableSnmpd(self):
        self.execdom0("systemctl disable snmpd")
            
    def enableSnmpd(self):
        self.execdom0("systemctl enable snmpd")

    def scsiIdPath(self):
        return "/usr/lib/udev/scsi_id"
            
    def iptablesSave(self):
        self.execdom0("/usr/libexec/iptables/iptables.init save")

    def enableVirtualFunctions(self):

        out = self.execdom0("grep -v '^#' /etc/modprobe.d/ixgbe.conf 2> /dev/null; echo -n ''" % ()).strip()
        if len(out) > 0:
            return

        numPFs = int(self.execdom0('lspci | grep 82599 | wc -l').strip())
        #we check ixgbe version so as to understand netsclaer VPX specific - NS drivers: in which case, configuration differs slightly. 
        ixgbe_version = self.execdom0("modinfo ixgbe | grep 'version:        '") 
        if numPFs > 0:
            if (re.search("NS", ixgbe_version.split()[1])):
                maxVFs = "63" + (",63" * (numPFs - 1))
            else:
                maxVFs = "40"
            self.execdom0('echo "options ixgbe max_vfs=%s" > "/etc/modprobe.d/ixgbe.conf"' % (maxVFs))

            self.execdom0('/bin/sh /boot/initrd-*.img.cmd')
            self.reboot()
            self.waitForSSH(300, desc="host reboot after enabling virtual functions")

    def getInstaller(self):
        if not self.installer:
            self.installer = xenrt.lib.xenserver.install.DundeeInstaller(self)
        return self.installer

    def install(self,
                *args,
                **kwargs):

        xenrt.TEC().logverbose("Using DundeeHost.install")

        self.getInstaller().install(*args, **kwargs)

    def writeUefiLocalBoot(self, nfsdir, pxe):
        if not self.lookup("PXE_CHAIN_UEFI_BOOT", False, boolean=True):
            pxe.uninstallBootloader(self.machine)
        else:
            with open("%s/bootlabel" % nfsdir.path()) as f:
                bootlabel = f.read().strip()
            xenrt.TEC().logverbose("Found %s as boot partition" % bootlabel)
            localEntry = """
                search --label --set root %s
                chainloader /EFI/xenserver/grubx64.efi
            """ % bootlabel
            pxe.addGrubEntry("local", localEntry)
            pxe.setDefault("local")
            pxe.writeOut(self.machine)

    def transformCommand(self, command):
        """
        Dundee requires disabling metadata_readonly flag to run raw storage command.
        To implement this overrideing GenericHost.transformCommand()

        @param command: The command that can be transformed.
        @return: transformed command
        """

        # From Dundee (and CentOS 7 dom0) requires special flag/options
        # to execute raw storage commands that modify storage including
        # volume, pv and lv.

        if any(imap(command.startswith, ["vgcreate",
                                    "vgchange",
                                    "vgremove",
                                    "vgextend",
                                    "lvrename",
                                    "lvcreate",
                                    "lvchange",
                                    "lvremove",
                                    "lvresize",
                                    "pvresize",
                                    "pvcreate",
                                    "pvchange",
                                    "pvremove",
                                    ])):
            command = command + " --config global{metadata_read_only=0}"

        return command

    def modifyRawStorageCommand(self, sr, command):
        """
        Evaluate SR and modify command to run via xenvm if given SR is
        a thin provisioning SR.
        Overriding Host.modifyRawStorageCommand

        @param command: command to run from dom0.
        @param sr: a storage repository object or sruuid.
        @return: a modified command
        """

        # Without knowing SR, cannot determine whether it requires modification.
        if not sr:
            return command

        # If NO_XENVMD is defined and set to 'yes' xenvm modification is not required.
        if xenrt.TEC().lookup("NO_XENVMD", False, boolean=True):
            return command

        # If given SR is not an SR instance consider it is a uuid and
        # get a Storage instance from uuid.
        if not isinstance(sr, xenrt.lib.xenserver.StorageRepository):
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(self, sr).fromExistingSR(self, sr)

        if sr.thinProvisioning and any(imap(command.startswith, ["lvchange",
                                            "lvcreate",
                                            "lvdisplay",
                                            "lvremove",
                                            "lvrename",
                                            "lvresize",
                                            "lvs",
                                            "pvremove",
                                            "pvs",
                                            "vgcreate",
                                            "vgremove",
                                            "vgs"
            ])):
            command = "xenvm " + command

        return command

    def installComplete(self, handle, waitfor=False, upgrade=False):
        CreedenceHost.installComplete(self, handle, waitfor, upgrade)
        if not upgrade and xenrt.TEC().lookup("STUNNEL_TLS", False, boolean=True):
            self.execdom0("xe host-param-set ssl-legacy=false uuid=%s" % self.getMyHostUUID())

        if xenrt.TEC().lookup("LIBXL_XENOPSD", False, boolean=True):
            self.execdom0("service xenopsd-xc stop")
            self.execdom0("sed -i s/vbd3/vbd/ /etc/xenopsd.conf")
            self.execdom0("chkconfig --del xenopsd-xc")
            self.execdom0("chkconfig --add xenopsd-xenlight")
            self.execdom0("sed -i -r 's/classic/xenlight/g' /etc/xapi.conf")
            self.restartToolstack()

        if xenrt.TEC().lookup("USE_HOST_IPV6", False, boolean=True):
            xenrt.TEC().logverbose("Setting %s's primary address type as IPv6" % self.getName())
            pif = self.execdom0('xe pif-list management=true --minimal').strip()
            self.execdom0('xe host-management-disable')
            self.execdom0('xe pif-set-primary-address-type primary_address_type=ipv6 uuid=%s' % pif)
            self.execdom0('xe host-management-reconfigure pif-uuid=%s' % pif)
            self.waitForSSH(300, "%s host-management-reconfigure (IPv6)" % self.getName())

    def installMelio(self):
        xenrt.lib.xenserver.MelioHelper([self]).installMelio()

    def getHAPath(self):
        if self.haPath:
            return self.haPath
        if self.execdom0("ls /usr/libexec/xapi/cluster-stack/xhad", retval="code") == 0:
            self.haPath = "/usr/libexec/xapi/cluster-stack/xhad"
        else:
            self.haPath = "/opt/xensource/xha"
        return self.haPath

    def setXenLogLevel(self):
        """Set Xen Log Level to all"""
        self.execdom0("/opt/xensource/libexec/xen-cmdline --set-xen loglvl=all guest_loglvl=all")
        self.reboot()

#############################################################################


class Pool(object):
    """A host pool."""
    def __init__(self, master):
        self.master = master
        if master:
            master.pool = self
        self.slaves = {}

        # XXX needs some cleanup
        self.sharedDB = None
        self.sharedDBiscsi = None
        self.tileTemplates = {}
        self.tileLock = threading.Lock()
        self.rollingUpgradeInProgress = False
        self.iscsi = None

        # Set some WLB parameter defaults
        self.wlbEnabled = False
        self.wlbURL = ""
        self.wlbUsername = ""
        self.wlbPassword = ""
        
        # Set some HA parameter defaults
        self.haEnabled = False
        self.haCommonConfig = {}
        self.haLiveset = []
        self.haSRTypes = ["lvmoiscsi", "lvmohba"]
        
        if self.getPoolParam("ha-enabled") == "true":
            self.getHAConfig()
            self.haEnabled = True

    def getDeploymentRecord(self):
        ret = {"members": []}
        if self.master:
            ret["master"] = self.master.getName()
            ret['members'].append(self.master.getName())

        for s in self.slaves.keys():
            ret['members'].append(self.slaves[s].getName())

        return ret
            
    
    def populateSubclass(self, x):
        x.master = self.master
        x.slaves = self.slaves
        x.sharedDB = self.sharedDB
        x.sharedDBiscsi = self.sharedDBiscsi
        x.tileTemplates = self.tileTemplates
        x.tileLock = self.tileLock
        for h in x.getHosts():
            h.pool = x

        x.haEnabled = self.haEnabled
        x.haCommonConfig = self.haCommonConfig
        x.haLiveset = self.haLiveset
        x.haSRTypes = self.haSRTypes
        x.wlbEnabled = self.wlbEnabled
        x.wlbURL = self.wlbURL
        x.wlbUsername = self.wlbUsername
        x.wlbPassword = self.wlbPassword

    def upgrade(self, newVersion=None, rolling=False):
        """Upgrade this pool to a later version.

           This will upgrade all the hosts in the pool. Note however that it
           will NOT update tools/drivers in guests.

           @param newVersion: The version we are upgrading to
           @param rolling: If set to C{True} we will performing a rolling
                           upgrade, i.e. we will evacuate each host before
                           upgrading it. If C{False}, the caller is responsible
                           for ensuring all guests are shut down.
           """
        if self.haEnabled:
            raise xenrt.XRTError("Cannot upgrade an HA enabled pool")
        
        if not newVersion:
            newVersion = productVersionFromInputDir(xenrt.TEC().getInputDir())

        # Construct a new pool object, and call its _upgrade method
        newPool = xenrt.lib.xenserver.poolFactory(newVersion)(self.master)
        self.populateSubclass(newPool)
        newPool._upgrade(newVersion, rolling)

        # Try and update the pool object in the registry (if present)
        try:
            xenrt.TEC().registry.poolReplace(self, newPool)
        except:
            pass

        return newPool

    def _upgrade(self, newVersion, rolling):
        # Record that we're performing a rolling upgrade
        self.rollingUpgradeInProgress = True

        # Update the master
        if rolling:
            self.master.evacuate()
        self.master = self.master.upgrade(newVersion=newVersion)
        self.master.waitForEnabled(300, desc="Wait for upgraded master to become enabled")
        self.master.check()
        if rolling:
            # Wait (with a 5 minute timeout) until all slaves have checked in
            st = xenrt.util.timenow()
            xenrt.TEC().logverbose("Waiting for all slaves to check in...")
            while True:
                if (xenrt.util.timenow() - st) > 300:
                    raise xenrt.XRTError("1 or more slaves did not check in "
                                         "within 5 minutes")
                allLive = True
                for s in self.slaves:
                    h = self.slaves[s]
                    if h.getHostParam("enabled") != "true" or \
                       h.getHostParam("host-metrics-live") != "true":
                        allLive = False
                        break
                if allLive:
                    xenrt.TEC().logverbose("...all slaves checked in")
                    break
                xenrt.sleep(10)

        self.upgradedHosts = [self.master]

        # Now update the slaves
        for s in self.slaves:
            h = self.slaves[s]
            if rolling:
                suspendedGuests = {}
                # Can't use evacuate, as it might try and migrate to a non
                # upgraded host
                xenrt.TEC().logverbose("Evacuating host %s" % (s))
                for g in h.listGuests(running=True):
                    xenrt.TEC().logverbose("Attempting to migrate VM %s..." % (g))
                    guuid = h.parseListForUUID("vm-list", "name-label", g)
                    cli = h.getCLIInstance()
                    # Try to migrate it to each host in turn (we do this as one might be full)
                    migrated = False
                    for nh in self.upgradedHosts:
                        try:
                            cli.execute("vm-migrate","uuid=%s host-uuid=%s live=true" %
                                                     (guuid, nh.getMyHostUUID()))
                            xenrt.TEC().logverbose("...migrated to %s" % (nh.getName()))
                            migrated = True
                            break
                        except:
                            xenrt.TEC().logverbose("Failure attempting to migrate to %s" % (nh.getName()))
                    if not migrated:
                        xenrt.TEC().warning("Unable to migrate VM %s, will suspend instead" % (g))
                        cli.execute("vm-suspend","uuid=%s" % (guuid))
                        suspendedGuests[g] = guuid
                for g in suspendedGuests:
                    xenrt.TEC().logverbose("Resuming VM %s" % (g))
                    cli = self.getCLIInstance()
                    cli.execute("vm-resume","uuid=%s" % (suspendedGuests[g]))
            self.slaves[s] = h.upgrade(newVersion=newVersion)
            self.slaves[s].waitForEnabled(300, desc="Wait for upgraded slave to become enabled")
            self.slaves[s].check()
            self.upgradedHosts.append(self.slaves[s])

        self.rollingUpgradeInProgress = False

        # Perform any post upgrade steps required
        xenrt.TEC().logverbose("Performing post upgrade steps")
        self.master.postUpgrade()
        for h in self.slaves.values():
            h.postUpgrade()
            
    def hostFactory(self):
        return xenrt.lib.xenserver.Host
    
    def listSlaves(self):
        """Return a list of names of slaves in this pool."""
        slaves = self.master.minimalList("host-list", "name-label")
        return filter(lambda x:x != self.master.getName(), slaves)

    def getSlavesStatus(self):
        """Return a dictionary of slave UUID -> status"""
        slaves = self.master.minimalList("host-list")
        slaves = filter(lambda x:x != self.master.getMyHostUUID(), slaves)
        ret = {}
        for slave in slaves:
            ret[slave] = self.master.parseListForParam("host-list",slave,
                                                       "host-metrics-live")
        return ret            

    def getHosts(self):
        """Returns a list of ALL host objects in the pool"""
        hosts = self.slaves.values()
        hosts.append(self.master)
        return hosts

    def getHostsCount(self):
        """Returns a count of host objects in the pool"""
        hosts = self.getHosts()
        return len(hosts)

    def getSlaves(self):
        """Returns a list of slave host objects in the pool"""
        hosts = self.slaves.values()
        return hosts

    def getHost(self, uuid):
        """Return the host object for the given UUID"""
        hosts = self.getHosts()
        for h in hosts:
            if h.getMyHostUUID() == uuid:
                return h
        return None

    def setupSharedDB(self):
        """Set the pool to use a shared database for configuration."""
        # XXX needs some cleanup
        host = self.master
        iscsi = xenrt.lib.xenserver.ISCSILun()
        self.sharedDBiscsi = iscsi
        if iscsi.chap:
            i, u, s = iscsi.chap
        else:
            u = "\"\""
            s = "\"\""

        self.sharedDB = "%s %s %s %s %s" % (iscsi.getServer(),u,s,
                                            iscsi.getTargetName(),"0")

        # Make sure all hosts in the pool have IQNs set
        host.setIQN(iscsi.getInitiatorName(allocate=True))
        for h in self.slaves.values():
            h.setIQN(iscsi.getInitiatorName(allocate=True))
        try:
            host.execdom0("/etc/init.d/xapi stop")
            host.execdom0("python /opt/xensource/sm/shared_db_util.py "
                          "xenrt-setup %s" % (self.sharedDB))
            iscsi.sharedDB = host # This is so it can be cleaned up later
            host.execdom0("/etc/init.d/xapi start")

        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Exception while setting up shared "
                                   "database: " + str(e),data=e.data)

        return iscsi


    def existing(self):
        slaves = self.listSlaves()
        for hostname in slaves:
            xenrt.TEC().logverbose("Looking for slave: %s" % (hostname))
            slave = self.hostFactory()(xenrt.PhysicalHost(hostname))
            xenrt.TEC().logverbose("Found existing host: %s" % (hostname))
            slave.findPassword()
            slave.checkVersion()
            i = 0
            while True:
                i = i + 1
                hosttag = "RESOURCE_HOST_%u" % (i)
                if not xenrt.TEC().registry.hostGet(hosttag):
                    break
            
            xenrt.TEC().logverbose("Adding %s (%s) to registry" % (hosttag, hostname))
            xenrt.GEC().registry.hostPut(hosttag, slave)
            xenrt.GEC().registry.hostPut(hostname, slave)
            self.slaves[hostname] = slave
            slave.pool = self
            if self.master.defaultsr:
                slave.defaultsr = self.master.defaultsr
            # Make sure that running guests have been given the right host
            sguests = slave.listGuests(running=True)
            for guestname in sguests:
                g = xenrt.TEC().registry.guestGet(guestname)
                g.host = slave
    
    def tailor(self):
        return

    def setMaster(self, host):
        oldMaster = self.master
        self.slaves[self.master.getName()] = self.master
        del self.slaves[host.getName()]
        self.master = host
        host.pool = self

        if self.sharedDB:
            reachable = False
            try:
                oldMaster.checkReachable()
                reachable = True
                oldMaster.execdom0("/etc/init.d/xapi stop || true")
                oldMaster.execdom0("umount /var/xapi/shared_db")
                oldMaster.execdom0("rm -f /etc/xensource/remote.db.conf")
                oldMaster.execdom0("/bin/cp -f /etc/xensource/local.db.conf"
                                   " /etc/xensource/db.conf")
            except:
                pass

            host.execdom0("/etc/init.d/xapi stop")
            host.execdom0("python /opt/xensource/sm/shared_db_util.py "
                          "xenrt-setup2 %s" % (self.sharedDB))
            self.iscsi.sharedDB = host
            host.execdom0("/etc/init.d/xapi start")

        cli = self.getCLIInstance()
        cli.execute("pool-emergency-transition-to-master")
        host.waitForXapi(35, desc="wait for Xapi")

        if self.sharedDB and reachable:
            try:
                oldMaster.execdom0("/etc/init.d/xapi start")
                xenrt.sleep(60)
            except:
                pass

    def designateNewMaster(self, host, metadataOnly=False):
        xenrt.TEC().logverbose("Designating new master %s" % (host.getName()))
        xenrt.TEC().logverbose("Previous master %s" % (self.master.getName()))
        oldMaster = self.master

        if not metadataOnly:         
            # If we have a remote database on the old master then disconnect
            lun = oldMaster.disableSharedDB()
        
            # Perform the master switch
            cli = self.getCLIInstance()
            try:
                cli.execute("pool-designate-new-master", "host-uuid=%s" %
                            (host.getMyHostUUID()))
            except xenrt.XRTException, e:
                if e.data and re.search("Lost connection to the server.", e.data):
                    pass
                else:
                    raise
            xenrt.sleep(300)
        
        # Update harness metadata
        self.slaves[self.master.getName()] = self.master
        del self.slaves[host.getName()]
        self.master = host
        host.pool = self

        if not metadataOnly:
            # Make sure the old master has host-metrics-live=true
            deadline = xenrt.timenow() + 600
            while True:
                try:
                    if oldMaster.getHostParam("host-metrics-live") == "true":
                        break
                except:
                    pass
                if xenrt.timenow() > deadline:
                    raise xenrt.XRTFailure("Timed out waiting for old master host-metrics-live")
                xenrt.sleep(30)
        
            # If we had a remote database then reconnect on the new master
            if lun:
                self.master.setupSharedDB(lun, existing=True)
            xenrt.sleep(360)
            self.check()

    def findMaster(self, notCurrent=False, timeout=180, waitOnChange=True,
                   warnOnWait=False):
        """Find the current pool master"""
        if notCurrent:
            current = self.master
            st = xenrt.util.timenow()
            warned = False
            while True:
                for h in self.getHosts():
                    m = self._getPoolMaster(h)
                    if m and m != current:
                        self.designateNewMaster(m,metadataOnly=True)
                        if waitOnChange:
                            xenrt.TEC().logverbose("Waiting 120 seconds for "
                                                   "master to settle...")
                            xenrt.sleep(120)
                        return m
                if warnOnWait and not warned:
                    xenrt.TEC().warning("Pool master had not changed when "
                                        "expected")
                    warned = True
                if (xenrt.util.timenow() - st) > timeout:
                    raise xenrt.XRTFailure("Pool master has not changed after "
                                           "%u seconds" % (timeout))
                xenrt.sleep(10)
        else:
            # Query hosts (allowing for no response) until we find one that
            # knows who the master is
            for h in self.getHosts():
                m = self._getPoolMaster(h)
                if m:
                    if m != self.master:
                        self.designateNewMaster(m,metadataOnly=True)
                        if waitOnChange:
                            xenrt.TEC().logverbose("Waiting 120 seconds for "
                                                   "master to settle...")
                            xenrt.sleep(120)
                    return m

            raise xenrt.XRTFailure("Unable to determine pool master")

    def _getPoolMaster(self, host):
        try:
            if self.haEnabled and not (host.getMyHostUUID() in self.haLiveset):
                # Don't trust anything this host knows about, as it's dead!
                return None
            pc = host.execdom0("cat /etc/xensource/pool.conf",timeout=10)
            if pc.strip() == "master":
                return host
            elif pc.strip().startswith("slave:"):
                l = pc.strip().split(":")
                masterip = l[1].strip()
                for h in self.getHosts():
                    if h.getIP() == masterip:
                        return h
                raise xenrt.XRTError("Pool master (%s) is not a known host" %
                                     (masterip))
            else:
                raise xenrt.XRTError("Unknown entry in pool.conf: %s" % 
                                     (pc.strip()))
        except xenrt.XRTFailure, e:
            return None
            
            

    def recoverSlaves(self):          
        cli = self.getCLIInstance()
        return cli.execute("pool-recover-slaves")        

    def getCLIInstance(self):
        if self.master:
            return self.master.getCLIInstance(local=True)
        raise xenrt.XRTError("Pool has no master defined")

    def getAPISession(self, username="root", password=None, slave=False, secure=True):
        """Return a logged in Xen API session to this pool"""
        if self.master:
            return self.master.getAPISession(username=username,
                                             password=password,
                                             local=True, slave=slave,
                                             secure=secure)
        raise xenrt.XRTError("Pool has no master defined")

    def logoutAPISession(self, session):
        """Logout from a Xen API session."""
        session.xenapi.session.logout()

    def getUUID(self):
        """Get the UUID of this pool"""
        masteruuid = self.master.getMyHostUUID()
        cli = self.getCLIInstance()
        return cli.execute("pool-list",
                           "master=%s" % (masteruuid),
                           minimal=True)

    def getPoolParam(self, param):
        """Get a pool parameter"""
        uuid = self.getUUID()
        cli = self.getCLIInstance()
        return cli.execute("pool-param-get",
                           "uuid=%s param-name=\"%s\"" % (uuid, param),
                           strip=True)

    def paramGet(self, param):
        return self.getPoolParam(param)

    def setPoolParam(self, param, value):
        uuid = self.getUUID()
        cli = self.getCLIInstance()
        cli.execute("pool-param-set",
                    "uuid=%s %s=\"%s\"" %
                    (uuid, param, str(value).replace('"', '\\"')))

    def paramSet(self, param, value):
        self.setPoolParam(param, value)

    def clearPoolParam(self, param):
        uuid = self.getUUID()
        cli = self.getCLIInstance()
        cli.execute("pool-param-clear", "uuid=%s param-name=%s" % (uuid, param))

    def removePoolParam(self, param, pkey):
        uuid = self.getUUID()
        cli = self.getCLIInstance()
        cli.execute("pool-param-remove", "uuid=%s param-name=%s param-key=%s" % 
                                         (uuid, param, pkey))

    def syncDatabase(self):
        cli = self.getCLIInstance()
        cli.execute("pool-sync-database")

    def getName(self):
        return self.getPoolParam("name-label")

    def dump(self, filename):
        cli = self.getCLIInstance()
        args = []
        args.append("file-name=%s" % (filename))
        cli.execute("pool-dump-database", string.join(args))

    def restore(self, filename):
        cli = self.getCLIInstance()
        args = []
        args.append("file-name=%s" % (filename))
        args.append("--force")
        cli.execute("pool-restore-database", string.join(args))
        # Wait for either xapi restart on older builds or host restart on newer ones
        xenrt.sleep(120)
        self.master.waitForSSH(600, desc="Host reboot after pool-restore-database")

    def check(self):
        hosts = self.master.minimalList("host-list")
        for h in self.slaves.values():
            if h.getMyHostUUID() not in hosts:
                raise xenrt.XRTFailure("Couldn't find slave %s in host list." % (h.getName()))
        if self.master.getMyHostUUID() not in hosts:
            raise xenrt.XRTFailure("Couldn't find master %s in host list." % (self.master.getName()))
        if not len(hosts) == len(self.slaves) + 1:
            raise xenrt.XRTFailure("Host length mismatch.")
        if not self.getPoolParam("master") == self.master.getMyHostUUID():
            raise xenrt.XRTFailure("Disagreement over master.")
        if not xenrt.TEC().lookup("POOL_NO_DEFAULT_SR", False, boolean=True):
            sruuid = self.getPoolParam("default-SR") 
        for h in self.slaves.values():
            if h.isOnline:
                h.checkReachable()
                if h.checkEmergency():
                    xenrt.TEC().logverbose("Slave %s in emergency mode" %
                                           (h.getName()))
                    raise xenrt.XRTFailure("A slave is in emergency mode")
            # TODO Check defaultsr is there.

    def forget(self, slave):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (slave.getMyHostUUID()))
        args.append("--force")
        cli.execute("host-forget", string.join(args))
        del self.slaves[slave.getName()]
        slave.pool = None
        xenrt.sleep(30)
        slavesr = self.master.parseListForUUID("sr-list", 
                                               "name-label",
                                               "Local storage on %s" % (slave.getName())) 
        slaveisos = self.master.parseListForUUID("sr-list", 
                                                 "name-label",
                                                 "CD/DVD drives on %s" % (slave.getName()))
        if slavesr:
            xenrt.TEC().warning("Pool still had slave local SR %s" % (slavesr))
            args = []
            args.append("uuid=%s" % (slavesr))
            cli.execute("sr-forget", string.join(args))
        if slaveisos:
            xenrt.TEC().warning("Pool still had slave ISO SR %s" % (slaveisos))
            args = []
            args.append("uuid=%s" % (slaveisos))
            cli.execute("sr-forget", string.join(args))
    
    def eject(self, slave):
        cli = self.getCLIInstance()
        args = []
        args.append("host-uuid=%s" % (slave.getMyHostUUID()))
        args.append("--force")
        cli.execute("pool-eject", string.join(args))

        xenrt.sleep(180)
        slave.pool = None
        del self.slaves[slave.getName()]

        timeout = 600

        # pool-eject causes the ejected host to reboot. Wait for this.
        for i in range(3):
            try:
                slave.waitForSSH(timeout, desc="Host %s reboot"
                                 % (slave.getName()))
            except xenrt.XRTException, e:
                if not re.search("timed out", e.reason):
                    raise e
                # Try again if this is a known BIOS/hardware boot problem
                if not slave.checkForHardwareBootProblem(True):
                    raise e
                slave.waitForSSH(timeout, desc="Host %s reboot"
                                 % (slave.getName()))
                
            # Check what we can SSH to is the rebooted host
            uptime = slave.execdom0("uptime")
            r = re.search(r"up (\d+) min", uptime)
            if r and int(r.group(1)) <= 10:
                if slave.special.has_key('v6licensing') and slave.special['v6licensing']:
                    # Using CA-33324 workaround
                    # Relicense to ensure we have the correct edition
                    edition = xenrt.TEC().lookup("OPTION_LIC_SKU", None)
                    xenrt.sleep(60)
                    if edition:
                        slave.license(edition=edition)
                    else:
                        slave.license()
                # pool-eject causes firstboot scripts to run again, so we need to
                # handle this
                if xenrt.TEC().lookup("WORKAROUND_CC_FWHTTP", False, boolean=True):
                    xenrt.TEC().warning("Altering CC firewall")
                    slave.execdom0("iptables -I OUTPUT -p tcp --dport 80 -m state "
                                  "--state NEW -d %s -j ACCEPT" %
                                  (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")))
                    slave.iptablesSave()
                return
            xenrt.sleep(60)
        raise xenrt.XRTFailure("Host %s has not rebooted" % (slave.getName()))
        # if xenrt.TEC().lookup("WORKAROUND_NIC_RESTART", False, boolean=True):
        #     if self.master.controller:
        #         self.master.controller.place.reboot()

    def addHost(self, slave, force=False, user="root", pw=None, bypassSSL=False):
        for sr in self.master.srs.values():
            sr.prepareSlave(self.master, slave)
        if self.master.lungroup:
            slave.setIQN(self.master.lungroup.getInitiatorName(allocate=True))

        cli = slave.getCLIInstance(local=True)
        if not pw:
            pw = self.master.password
        if not pw:
            pw = xenrt.TEC().lookup("ROOT_PASSWORD")
        args = []
        args.append("master-address=%s" % (self.master.getIP()))
        args.append("master-username=%s" % (user))
        args.append("master-password=%s" % (pw))
        if xenrt.TEC().lookup("WORKAROUND_CA6704", False, boolean=True):
            xenrt.TEC().logverbose("Using CA-6704 workaround")
            args.append("--force")
        elif force:
            args.append("--force")
        cli.execute("pool-join", string.join(args))

        slave.pool = self
        self.slaves[slave.getName()] = slave
        if self.master.defaultsr:
            slave.defaultsr = self.master.defaultsr

        # Guests on the slave will have had their UUID changed so remove our
        # cache of them.
        for g in slave.guests.values():
            g.uuid = None

        # Don't return until the slave is shown as enabled
        slave.waitForEnabled(900, desc="Wait for slave host to be enabled")
        if xenrt.TEC().lookup("WORKAROUND_NIC_RESTART", False, boolean=True):
            if self.master.controller:
                self.master.controller.place.reboot()
        
    def updateHostObject(self, old, new):
        """Replace one host object with another."""
        if self.master == old:
            self.master = new
        if self.slaves.has_key(old.getName()):
            self.slaves[new.getName()] = new

    def checkEmergency(self):
        for slave in self.slaves.values():
            cli = slave.getCLIInstance(local=True)
            emode = None
            try:
                emode = cli.execute("host-is-in-emergency-mode")
            except:
                # Use legacy method
                data = cli.execute("host-list", ignoreerrors=True)
                if not re.search("emergency", data):
                    if re.search("The host is still booting", data):
                        xenrt.TEC().warning("Using emergency mode check "
                                            "workaround")
                    else:
                        return False
            if emode:
                if not re.search("true", emode):
                    return False

        return True

    def addSRToPool(self, sr, default=True):
        """Adds a shared SR to the pool and sets the default params if
        required"""
        self.master.addSR(sr, default=default)
        if default: 
            self.setPoolParam("default-SR", sr.uuid)
            self.setPoolParam("crash-dump-SR", sr.uuid)
            self.setPoolParam("suspend-image-SR", sr.uuid)
            for slave in self.slaves.values():
                slave.defaultsr = self.master.defaultsr

    def setIQNs(self, lungroup):
        """Give each host in the pool an initiator name from the lungroup
        specification."""
        self.master.setIQN(lungroup.getInitiatorName(allocate=True))
        for h in self.slaves.values():
            h.setIQN(lungroup.getInitiatorName(allocate=True))

    def configureSSL(self, enableVerification=True):
        raise xenrt.XRTError("SSL can only be configured on an MNR pool or above")

    def enableHA(self, params={}, srs=[], check=True):
        """Enables High Availability on the pool""" 
        if len(srs) == 0:
            if len(filter(lambda t: len(self.master.getSRs(type=t)) > 0, self.haSRTypes)) == 0:
                raise xenrt.XRTError("Must have one of the following SR type: %s" % self.haSRTypes)

        hosts = list(self.slaves.values())
        hosts.append(self.master)

        confString = ""
        for p in params.keys():
            confString += " ha-config:%s=%s" % (p,params[p])
        if srs:
            confString += " heartbeat-sr-uuids=%s" % (string.join(srs,","))

        cli = self.getCLIInstance()
        cli.execute("pool-ha-enable%s" % (confString))
        xenrt.sleep(45) # Statefile can take a wee bit longer to update (CA-92623)

        self.getHAConfig()
        self.getHALiveSet()
        self.haEnabled = True
        if check:
            self.checkHA()

    def disableHA(self, check=True):
        """Disables High Availability on the pool"""
        cli = self.getCLIInstance()
        cli.execute("pool-ha-disable")
        self.haEnabled = False
        if check:
            self.checkHA()

    def getHAConfig(self):
        """Get the High Availability configuration from the pool"""
        # Read the xhad.conf file from the master, and update haCommonConfig,
        # plus the hosts haLocalConfig (XXX Need to check this is the right 
        # location)
        xhc = self.master.execdom0("cat /etc/xensource/xhad.conf").strip()
        dom = xml.dom.minidom.parseString(xhc)
        self.haCommonConfig = self.parseCommonHAConfig(dom)
        self.master.parseLocalHAConfig(dom)
        
        # Go through every slave and read xhad.conf - verify common config
        # matches and update the hosts haLocalConfig
        for s in self.slaves.values():
            xhc = s.execdom0("cat /etc/xensource/xhad.conf").strip()
            dom = xml.dom.minidom.parseString(xhc)
            haCC = self.parseCommonHAConfig(dom)
            if haCC != self.haCommonConfig:
                raise xenrt.XRTFailure("Slave %s disagrees with master "
                                       "about HA common config" % (s.getName()))
            s.parseLocalHAConfig(dom)

        # Also get the HA statefile VDI UUIDs
        self.haCommonConfig['statefileVDIs'] = \
                                 self.master.minimalList("pool-list",
                                                         params="ha-statefiles")
        # Determine what type the VDI is
        vdi = self.haCommonConfig['statefileVDIs'][0]
        sr = self.master.getVDISR(vdi)
        self.haCommonConfig['statefileType'] = self.master.getSRParam(sr, "type")

    def parseCommonHAConfig(self, dom):
        # Get the common-config element
        config = {'hosts': {}}
        try:
            cc = dom.getElementsByTagName("common-config")[0]
            for n in cc.childNodes:
                if n.nodeName == "GenerationUUID":
                    config[n.nodeName] = n.childNodes[0].data.strip()
                elif n.nodeName == "UDPport":
                    config[n.nodeName] = n.childNodes[0].data.strip()
                elif n.nodeName == "host":
                    hosts = config['hosts']
                    hosts[n.getElementsByTagName("HostID")[0].childNodes[0].data] = \
                        n.getElementsByTagName("IPaddress")[0].childNodes[0].data
                    config['hosts'] = hosts
                elif n.nodeName == "parameters":            
                    for cn in n.childNodes:
                        if cn.nodeName != "#text":
                            config[cn.nodeName] = cn.childNodes[0].data
        except Exception, e:
            raise xenrt.XRTError("Exception while parsing HA XML config file" +
                                 str(e))

        return config

    def getHALiveSet(self,host=None,update=True):
        """Get the current view of the liveset from the HA daemon"""
        # If we haven't specified a host, use the master
        if not host:
            host = self.master
        liveset = []

        xli = host.execdom0("PATH=$PATH:%s "
                            "%s/ha_query_liveset" % (host.getHAPath(), host.getHAPath())).strip()
        dom = xml.dom.minidom.parseString(xli)
        hli = dom.getElementsByTagName("ha_liveset_info")[0]
        for n in hli.childNodes:
            if n.nodeName == "host":                
                uuid = n.getElementsByTagName("HostID")[0].childNodes[0].data
                liveness = n.getElementsByTagName("liveness")[0].childNodes[0].data
                if liveness == "TRUE":
                    liveset.append(uuid)                           

        if update:
            # Update self.haLiveset
            self.haLiveset = liveset

        return liveset

    def parseHAStateFile(self, host=None, noLoops=0):
        """Parse the HA state file"""
        # If we haven't specified a host to use, use the master
        if not host:
            host = self.master

        # Use the dumpstatefile utility to read in the state file
        # XXX Hard coded config file location
        dict = {'hosts':{}}
        try:
            data = host.execdom0("%s/dumpstatefile "
                                 "/etc/xensource/xhad.conf" % (host.getHAPath()))
            lines = data.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("**"):
                    # We've had a checksum problem, let's try again
                    if noLoops > 2:
                        raise xenrt.XRTFailure("Checksum error after 3 "
                                               "attempts: %s" % (line))

                    xenrt.sleep(1)
                    return self.parseHAStateFile(host=host, 
                                                 noLoops=noLoops+1)
                elif line.startswith("-") or line == "":
                    continue
                elif line.startswith("global."):
                    l = line.split("=")
                    key = l[0].split(".")[1].strip()
                    value = l[1].strip()
                    dict[key] = value
                elif line.startswith("host["):
                    l = line.split("=")
                    host = int(l[0].split("[")[1].split("]")[0].strip())
                    key = l[0].split(".")[1].strip()
                    value = l[1].strip()
                    hosts = dict['hosts']
                    if not hosts.has_key(host):
                        hosts[host] = {}
                    hosts[host][key] = value
                else:
                    raise xenrt.XRTError("Unrecognised line in dumpstatefile "
                                         "output: %s" % (line))
        except Exception, e:
            if isinstance(e, xenrt.XRTException):
                raise e
            else:
                traceback.print_exc(file=sys.stderr)
                raise xenrt.XRTError("Exception while parsing statefile: %s" %
                                     (str(e)))

        return dict

    def checkHA(self, host=None):
        """Verify our view of the HA world is correct"""

        if not self.haEnabled:
            # Check we don't have any HA daemons running etc
            for h in self.getHosts():
                if h.isOnline and h.execdom0("ps -ef | grep [x]had > /dev/null",
                                             retval="code") == 0:
                    # (we don't put the host in the failure message so bug
                    #  filing is more accurate)
                    xenrt.TEC().logverbose("xhad found on host %s" % (h.getName()))
                    raise xenrt.XRTFailure("xhad found even though HA is "
                                           "disabled")

            return

        if len(self.haLiveset) == 0:
            # Special case, all hosts should be self-fenced
            # If we can connect to any, check they booted recently and that
            # xapi isn't running
            for h in self.getHosts():
                failed = False
                try:
                    if h.execdom0("ps -ef | grep \"bin/[x]api \"",
                                  retval="code") == 0:
                        failed = True
                except:
                    pass
                if failed:
                    raise xenrt.XRTFailure("Host %s running xapi but "
                                           "liveset should be empty" % 
                                               (h.getName()))
            # No point checking anything else!
            return

        # Verify that the state file shows what we expect...

        if not host:
            host = self.master

        if host.haStatefileBlocked:
            # Try and find another host...
            hosts = self.getHosts()
            for h in hosts:
                if (not h.haStatefileBlocked) and \
                   h.getMyHostUUID() in self.haLiveset:
                    host = h
                    break

        if host.haStatefileBlocked:
            xenrt.TEC().warning("All live hosts have statefile blocked so "
                                "cannot parse statefile")
        else:
            sfdict = self.parseHAStateFile(host=host)
            ver = sfdict['version']
            if ver == "1" or ver == "2":
                if sfdict['length_global'] != "4096":
                    raise xenrt.XRTError("Statefile global size is %s, should "
                                         "be 4096" % (sfdict['length_global']))
                if sfdict['length_host_specfic'] != "4096":
                    raise xenrt.XRTError("Statefile host size is %s, should be "
                                         "4096" % 
                                         (sfdict['length_host_specific']))
                if sfdict['max_hosts'] != "64":
                    raise xenrt.XRTError("Statefile max hosts is %s, should be "
                                         "64" % (sfdict['max_hosts']))
                hagenuuid = self.haCommonConfig['GenerationUUID'].replace("-",
                                                                          "")
                if sfdict['gen_uuid'] != hagenuuid:
                    raise xenrt.XRTError("Generation UUID (%s) does not match "
                                         "UUID in config file %s" % 
                                         (sfdict['gen_uuid'],hagenuuid))
                # Check each host element
                self.sleepHA("t2", extra=2) # Wait for statefile to have been updated
                newsfdict = self.parseHAStateFile(host=host)
                hosts = sfdict['hosts']
                newhosts = newsfdict['hosts']
                for hindex in hosts.keys():
                    # Get the UUID from the index                    
                    hdict = hosts[hindex]
                    huuid = xenrt.util.fixUUID(hdict['host_uuid'])
                    newhdict = newhosts[hindex]
                    h = self.getHost(huuid)

                    # Check sequence number has done the correct thing
                    sn = int(hdict['sequence'])   
                    newsn = int(newhdict['sequence'])
                    if h.haStatefileBlocked or (not huuid in self.haLiveset):
                        # Shouldn't have changed
                        if sn != newsn:
                            raise xenrt.XRTFailure("Sequence number in "
                                                   "statefile for element "
                                                   "corresponding to host %s "
                                                   "unexpectedly updated" %
                                                   (h.getName()))
                    else:
                        # Should have changed
                        if sn == newsn:
                            raise xenrt.XRTFailure("Sequence number in "
                                                   "statefile for element "
                                                   "corresponding to host %s "
                                                   "unexpectedly not updated" %
                                                   (h.getName()))

                        # Any failures in the following checks should not cause
                        # us to immediately bail out...
                        ok = True
                        failures = {'sfile':[],'hbeat':[],'lset':[]}

                        # Check it has the correct view of other hosts
                        poolHosts = self.getHosts()
                        # Hosts are indexed based on UUIDs
                        poolHosts.sort(lambda x,y: cmp(x.getMyHostUUID(),
                                                       y.getMyHostUUID()))
                        
                        lset = ""
                        ohi = -1
                        for oh in poolHosts:
                            ohi += 1
                            if oh.getMyHostUUID() in self.haLiveset:
                                lset += "1"
                            else:
                                lset += "0"       
                            if oh == h:
                                continue

                            # Check statefile update time makes sense
                            t = int(hdict['since_last_sf_update[%2u]' % (ohi)])
                            if not (oh.haStatefileBlocked or \
                               (not oh.getMyHostUUID() in self.haLiveset)):
                                if t < 0 or \
                                   t > ((self.getHATimeout("t2") * 2000) + 1000):
                                    ok = False
                                    failures['sfile'].append("Host %s "
                                        "unexpectedly believes that host %s "
                                        "has not updated state file for %u ms" %
                                        (h.getName(),oh.getName(),t))
                            else:
                                if t >= 0 and \
                                   t <= ((self.getHATimeout("t2") * 2000) + 1000):
                                    ok = False
                                    failures['sfile'].append("Host %s "
                                        "unexpectedly believes that host %s "
                                        "updated statefile %u ms ago" %
                                        (h.getName(),oh.getName(),t))

                            # Check heartbeat update time makes sense
                            if not (oh.haHeartbeatBlocks['allto'] or \
                               (h in oh.haHeartbeatBlocks['to']) or \
                               h.haHeartbeatBlocks['allfrom'] or \
                               (oh in h.haHeartbeatBlocks['from']) or \
                               (not oh.getMyHostUUID() in self.haLiveset)):
                                t = int(hdict['since_last_hb_receipt[%2u]' % (ohi)])
                                if t < 0 or \
                                   t > ((self.getHATimeout("t1") * 2000) + 1000):
                                    ok = False
                                    failures['hbeat'].append("Host %s "
                                        "has unexpectedly not received any "
                                        "heartbeats from %s for %u ms" %
                                        (h.getName(),oh.getName(),t))
                            else:
                                if t >= 0 and \
                                   t <= ((self.getHATimeout("t1") * 2000) + 1000):
                                    ok = False
                                    failures['hbeat'].append("Host %s "
                                        "has unexpectedly received a "
                                        "heartbeat from %s %u ms ago" %
                                        (h.getName(),oh.getName(),t))

                        # Check host has correct view of liveset
                        hls = hdict['current_liveset'].replace("-","")
                        # Parse this "bitmap l->h(01)"
                        m = re.match(".*\((\d+)\)", hls)
                        hls = m.group(1)
                        if hls != lset:
                            ok = False
                            failures['lset'].append("Expecting liveset %s, "
                                                    "found %s" % (lset,hls))

                        if not ok:
                            msg = "Unexpected HA State:"
                            if len(failures['sfile']) > 0:
                                msg += " statefile_updates"
                                for f in failures['sfile']:
                                    xenrt.TEC().logverbose(f)
                            if len(failures['hbeat']) > 0:
                                msg += " heartbeat_updates"
                                for f in failures['hbeat']:
                                    xenrt.TEC().logverbose(f)
                            if len(failures['lset']) > 0:
                                msg += " liveset"
                                for f in failures['lset']:
                                    xenrt.TEC().logverbose(f)
                            raise xenrt.XRTFailure(msg)

            else:
                raise xenrt.XRTError("state-file has unknown version %s" %
                                     (ver))

        currentLiveset = self.getHALiveSet(host=host,update=False)
        currentLiveset.sort()
        self.haLiveset.sort()
        if currentLiveset != self.haLiveset:
            raise xenrt.XRTFailure("Expecting liveset %s, found %s" % 
                                   (self.haLiveset,currentLiveset))

    def blockAllStatefiles(self, block=True):
        """(Un)block statefile access completely for all hosts"""
        for h in self.getHosts():
            h.blockStatefile(block=block)

    def blockAllHeartbeats(self, block=True, enable=True):
        """(Un)block heartbeat traffic completely for all hosts"""
        for h in self.getHosts():
            h.blockHeartbeat(block=block,enable=enable)

    def enableHeartbeatBlocks(self):
        for h in self.getHosts():
            h.execdom0("iptables -I INPUT -j XRTheartbeatIN > /dev/null 2>&1 "
                       "|| true")
            h.execdom0("iptables -I OUTPUT -j XRTheartbeatOUT > /dev/null 2>&1 "
                       "|| true")

    def disableHeartbeatBlocks(self):
        for h in self.getHosts():
            h.execdom0("iptables -D INPUT -j XRTheartbeatIN > /dev/null 2>&1 "
                       "|| true")
            h.execdom0("iptables -D OUTPUT -j XRTheartbeatOUT > /dev/null 2>&1 "
                       "|| true")

    def sleepHA(self, key, extra=5, multiply=None):
        """Sleep for an appropriate amount of time for key, with extra on top"""
        to = self.getHATimeout(key)
        if to:
            if multiply:
                xenrt.sleep(to * multiply)
            else:
                xenrt.sleep(to + extra)
        else:
            raise xenrt.XRTError("Unknown HA timeout %s" % (key))            
        if key == "W" and xenrt.TEC().lookup("WORKAROUND_CA86961", True, boolean=True):
            # Allow a further 3 minutes
            xenrt.TEC().warning("Working around CA-86961 by waiting an extra 3 minutes")
            xenrt.sleep(180)

    def getHATimeout(self, key):
        if key == "T1":
            if self.haCommonConfig.has_key("HeartbeatTimeout"):
                return int(self.haCommonConfig["HeartbeatTimeout"])
            return 30
        elif key == "t1":
            if xenrt.TEC().lookup("HA_GENEROUS_TIMEOUTS", False, boolean=True):
                add = 2
            else:
                add = 0
            if self.haCommonConfig.has_key("HeartbeatInterval"):
                return int(self.haCommonConfig["HeartbeatInterval"]) + add
            to = (self.getHATimeout("T1") + 10) / 10
            if to > 6:
                to = 6
            elif to < 2:
                to = 2
            return to + add
        elif key == "Wh":
            if self.haCommonConfig.has_key("HeartbeatWatchdogTimeout"):
                return int(self.haCommonConfig["HeartbeatWatchdogTimeout"])
            return self.getHATimeout("T1") + 15
        elif key == "T2":
            if self.haCommonConfig.has_key("StateFileTimeout"):
                return int(self.haCommonConfig["StateFileTimeout"])
            return 30
        elif key == "t2":
            if xenrt.TEC().lookup("HA_GENEROUS_TIMEOUTS", False, boolean=True):
                add = 2
            else:
                add = 1
            if self.haCommonConfig.has_key("StateFileInterval"):
                return int(self.haCommonConfig["StateFileInterval"]) + add
            to = (self.getHATimeout("T2") + 10) / 10
            if to > 6:
                to = 6
            elif to < 2:
                to = 2
            return to + add
        elif key == "Ws":
            if self.haCommonConfig.has_key("StateFileWatchdogTimeout"):
                return int(self.haCommonConfig["StateFileWatchdogTimeout"])
            return self.getHATimeout("T2") + 15
        elif key == "T":
            return max(self.getHATimeout("T1"),self.getHATimeout("T2"))
        elif key == "t":
            to = (self.getHATimeout("T") + 10) / 10
            if to > 6:
                to = 6
            elif to < 2:
                to = 2
            return to
        elif key == "W":
            return self.getHATimeout("T") + 15
        elif key == "X":
            if self.haCommonConfig.has_key("XapiHealthCheckTimeout"):
                return int(self.haCommonConfig["XapiHealthCheckTimeout"])
            return 120
        else:
            return None

    def applyPatch(self, patchfile, returndata=False, applyGuidance=False, patchClean=False):
        """Upload and apply a patch to the pool"""
        
        for h in self.getHosts():
            h.addHotfixFistFile(patchfile)

        cli = self.getCLIInstance()
        xenrt.TEC().logverbose("Applying patch %s" % (patchfile))
        
        patch_uuid = cli.execute("patch-upload", "file-name=\"%s\"" % (patchfile)).strip()
        
        if not patch_uuid:
            xenrt.TEC().logverbose("Didn't get UUID from patch-upload command")
            patch_uuid = self.master.minimalList("patch-list", args="name-label=\"%s\"" % (os.path.basename(patchfile)))[0]
        
        afterApplyGuidance = self.master.genParamGet("patch", patch_uuid, "after-apply-guidance")
        data = cli.execute("patch-pool-apply", "uuid=\"%s\"" %(patch_uuid))
        
        if applyGuidance:
            if "restartHost" in afterApplyGuidance:
                xenrt.TEC().logverbose("Rebooting master %s after patch-apply based on after-apply-guidance" % (self.master.getName()))
                self.master.reboot()
                
                for slave in self.getSlaves():
                    xenrt.TEC().logverbose("Rebooting slave %s after patch-apply based on after-apply-guidance" % (slave.getName()))
                    slave.reboot()
            
            elif "restartXAPI" in afterApplyGuidance:
                xenrt.TEC().logverbose("Restarting toolstack on master %s after patch-apply based on after-apply-guidance" % (self.master.getName()))
                self.master.restartToolstack()
            
                for slave in self.getSlaves():
                    xenrt.TEC().logverbose("Restarting toolstack on slave %s after patch-apply based on after-apply-guidance" % (slave.getName()))
                    slave.restartToolstack()
                
        if patchClean:
            cli.execute("patch-pool-clean", "uuid=\"%s\"" %(patch_uuid))
            
        if returndata:
            return data

    def messageCreate(self, name, body, priority=1):
        self.master.messageGeneralCreate("pool",
                                         self.getUUID(),
                                         name,
                                         body,
                                         priority)
    
    def enableAuthentication(self, authserver, useapi=False, setDNS=True, disable_modules=False):
        
        use_tcpdump = False

        if xenrt.TEC().lookup("DEBUG_CA41874", False, boolean=True):
            use_tcpdump = True
            
        if setDNS:
            for host in self.slaves.values() + [self.master]:
                host.setDNSServer(authserver.place.getIP())
        if useapi:
            session = self.getAPISession()
            try:
                config = {}
                config["domain"] = authserver.domainname
                config["user"] = authserver.place.superuser
                config["pass"] = authserver.place.password
                
                if use_tcpdump:
                    xenrt.TEC().warning("Using DEBUG_CA41874")
                    self.master.execdom0("mkdir -p /var/log/tcp_dump/; "
                                         "nohup tcpdump -w /var/log/tcp_dump/log_`date +%F_%k-%M-%S_%N` -s 0 tcp or udp  &> /dev/null < /dev/null & "
                                         "sleep 5; pidof tcpdump; exit 0")

                xenrt.TEC().logverbose("Using XenAPI to "
                                       "pool.enable_external_auth "
                                       "on %s/%s with config: %s" %
                                       (authserver.type,
                                        authserver.domainname,
                                        str(config)))
                xapi = session.xenapi
                poolref = xapi.pool.get_by_uuid(self.getUUID())
                xapi.pool.enable_external_auth(poolref,
                                               config,
                                               authserver.domainname,
                                               authserver.type)
            finally:
                self.logoutAPISession(session)
                if use_tcpdump:
                    self.master.execdom0('killall tcpdump; exit 0')
        else:
            cli = self.getCLIInstance()
            args = []
            args.append("uuid=%s" % (self.getUUID()))
            args.append("auth-type=%s" % (authserver.type))
            args.append("service-name=%s" % (authserver.domainname))

            if use_tcpdump:
                xenrt.TEC().warning("Using DEBUG_CA41874")
                self.master.execdom0("mkdir -p /var/log/tcp_dump/; "
                                     "nohup tcpdump -w /var/log/tcp_dump/log_`date +%F_%k-%M-%S_%N` -s 0 tcp or udp  &> /dev/null < /dev/null & exit 0")
                
            if authserver.type == "AD":
                args.append("config:domain=%s" % (authserver.domainname))
                args.append("config:user=%s" % (authserver.place.superuser))
                args.append("config:pass=%s" % (authserver.place.password))
            if disable_modules:
                args.append("config:disable_modules=%s" % (disable_modules))
            try:
                cli.execute("pool-enable-external-auth", string.join(args)).strip()
            except xenrt.XRTException, e:
                if e.data and "External authentication in this pool is already enabled for at least one host." in e.data:
                    pass
                else:
                    raise
            finally:
                if use_tcpdump:
                    self.master.execdom0('killall tcpdump; exit 0')

    def disableAuthentication(self, authserver, disable=False):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getUUID()))
        if disable:
            args.append("config:user=%s" % (authserver.place.superuser))
            args.append("config:pass=%s" % (authserver.place.password))
        cli.execute("pool-disable-external-auth", string.join(args)).strip()
        for host in self.slaves.values() + [self.master]:
            host.resetToDefaultNetworking()

    def addRole(self, subject, role):
        self.master.addRole(subject, role)
        # CA-33009 - Allow time for role changes to propagate across the pool.
        xenrt.sleep(60)

    def removeRole(self, subject, role):
        self.master.removeRole(subject, role)

    def allow(self, subject, role=None, useapi=False):
        self.master.allow(subject, role=role, useapi=useapi)

    def deny(self, subject):
        self.master.deny(subject)

    #########################################################################
    # Kirkwood / WLB related methods
    def initialiseWLB(self, wlb_url, wlb_username, wlb_password,
                      xs_username=None, xs_password=None, enable=True,
                      updateMetadata=True, check=True):
        """Configure and enable WLB integration"""

        # Do we need to provide the default password
        if not xs_username:
            xs_username = "root"
        if not xs_password:
            self.master.findPassword()
            xs_password = self.master.password
        cli = self.getCLIInstance()
        args = []
        args.append("wlb_url=\"%s\"" % (wlb_url))
        args.append("wlb_username=\"%s\"" %
                    (xenrt.util.sanitiseForBash(wlb_username)))
        args.append("wlb_password=\"%s\"" %
                    (xenrt.util.sanitiseForBash(wlb_password)))
        args.append("xenserver_username=\"%s\"" %
                    (xenrt.util.sanitiseForBash(xs_username)))
        args.append("xenserver_password=\"%s\"" %
                    (xenrt.util.sanitiseForBash(xs_password)))
        if self.master.productVersion == 'Orlando':           
            cli.execute("pool-initialise-wlb", string.join(args))
        else:
            cli.execute("pool-initialize-wlb", string.join(args))

        if updateMetadata:
            self.wlbURL = wlb_url
            self.wlbUsername = wlb_username
            self.wlbPassword = wlb_password

        if enable:
            self.enableWLB()
   
        if check:
            self.checkWLB()

    def deconfigureWLB(self):
        """Permanently disable WLB integration"""
        cli = self.getCLIInstance()
        cli.execute("pool-deconfigure-wlb")

        self.wlbEnabled = False
        self.wlbURL = ""
        self.wlbUsername = ""
        self.wlbPassword = ""

        self.checkWLB()

    def disableWLB(self):
        """Temporarily disable WLB integration"""
        self.setPoolParam("wlb-enabled", "false")
        self.wlbEnabled = False
        self.checkWLB()

    def enableWLB(self):
        """(Re-)enable WLB integration"""
        self.setPoolParam("wlb-enabled", "true")
        self.wlbEnabled = True
        self.checkWLB()

    def checkWLB(self):
        """Check the WLB configuration is as expected"""
        if self.wlbEnabled:
            checkFor = "true"
        else:
            checkFor = "false"

        if self.getPoolParam("wlb-enabled") != checkFor:
            raise xenrt.XRTFailure("WLB is not enabled")        
        
        if self.getPoolParam("wlb-url") != self.wlbURL:
            raise xenrt.XRTFailure("wlb-url is not as expected",
                                   data="expecting %s, actual %s" % 
                                        (self.wlbURL,
                                         self.getPoolParam("wlb-url")))

        if self.getPoolParam("wlb-username") != self.wlbUsername:
            raise xenrt.XRTFailure("wlb-username is not as expected",
                                   data="expecting %s, actual %s" %
                                        (self.wlbUsername,
                                         self.getPoolParam("wlb-username")))

    def sendWLBConfig(self, config):
        """Send a dictionary to WLB"""
        args = ""
        for c in config:
            args += "config:\"%s\"=\"%s\" " % (xenrt.util.sanitiseForBash(c),
                                          xenrt.util.sanitiseForBash(config[c]))
        args = args.strip()
        cli = self.getCLIInstance()
        cli.execute("pool-send-wlb-configuration", args)

    def retrieveWLBConfig(self):
        """Retrieve a dictionary from WLB"""
        cli = self.getCLIInstance()
        data = cli.execute("pool-retrieve-wlb-configuration")
        return xenrt.util.strlistToDict(data.splitlines(), sep=":", keyonly=False)

    def retrieveWLBRecommendations(self):
        """Retrieve recommendations from WLB"""
        cli = self.getCLIInstance()
        data = cli.execute("pool-retrieve-wlb-recommendations")
        recs = xenrt.util.strlistToDict(data.splitlines()[1:], sep=":", keyonly=False)
        #CA-80791
        recs = dict(map(lambda x:(re.sub(r'\(.+\)$', '', x),recs[x]), recs))
        return recs

    def retrieveWLBDiagnostics(self):
        """Retrieve log file contents from WLB"""
        cli = self.getCLIInstance()
        data = cli.execute("pool-retrieve-wlb-diagnostics")
        return xenrt.util.strlistToDict(data.splitlines(), sep=":", keyonly=False)

    def retrieveWLBReport(self, report, filename=None, params={}):
        """Retrieve the specified WLB report into the specified file"""
        cli = self.getCLIInstance()
        args = []
        args.append("report='%s'" % (report))
        if filename:
            args.append("filename='%s'" % (filename))
        for p in params:
            args.append("\"%s\"=\"%s\"" % (xenrt.util.sanitiseForBash(p),
                                     xenrt.util.sanitiseForBash(params[p])))
        return cli.execute("pool-retrieve-wlb-report", string.join(args))

#############################################################################

def watchForInstallCompletion(installs):
    waiting = {}
    for x in installs:
        host, handle = x
        nfsdir, packdir, pxe, uefi = handle
        filename = "%s/.xenrtsuccess" % (nfsdir.path())
        waiting[filename] = (host, pxe)

    # Watch for install completion of all hosts
    deadline = xenrt.timenow() + 1800
    while True:
        if len(waiting) == 0:
            return
        if xenrt.timenow() > deadline:
            for x in waiting.values():
                host, pxe = x
                xenrt.TEC().reason("Timed out waiting for %s install to "
                                   "complete" % (host.getName()))
            raise xenrt.XRTFailure("Timed out waiting for %u host install(s)"
                                   "to complete" % (len(waiting)))
        for filename in waiting.keys():
            if os.path.exists(filename):
                host, pxe = waiting[filename]
                host.checkHostInstallReport(filename)
                xenrt.TEC().progress("Installation complete on %s, waiting "
                                     "for host boot." % (host.getName()))
                # Boot the local disk  - we need to update this before the
                # machine reboots after setting the signal flag.
                if uefi:
                    host.writeUefiLocalBoot(nfsdir, pxe)

                pxe.setDefault("local")
                pxe.writeOut(host.machine)
                del waiting[filename]

        xenrt.sleep(15)


#############################################################################


class MNRPool(Pool):
    """A pool of MNR or Cowley hosts"""

    def __init__(self, master):
        Pool.__init__(self, master)
        self.dmcEnabled = False
        self.ca = None

    def populateSubclass(self, x):
        Pool.populateSubclass(self, x)
        x.dmcEnabled = self.dmcEnabled
        x.ca = self.ca

    def existing(self):
        Pool.existing(self)
        for slave in self.getSlaves():
            slave.existing(doguests=False)

    def hostFactory(self):
        return xenrt.lib.xenserver.MNRHost

    def addHost(self, slave, force=False, user="root", pw=None, bypassSSL=False):
        if self.ca and not bypassSSL:
            # Set the host up with appropriate certificates before joining it
            slave.installCertificate(self.ca.certificate)
            pem = self.ca.createHostPEM(slave, cn=slave.getIP(), sanlist=["127.0.0.1"])
            slave.installPEM(pem, waitForXapi=True)
            if not slave.isSSLVerificationEnabled():
                slave.enableSSLVerification()
        Pool.addHost(self, slave, force=force, user=user, pw=pw)

    def enableDMC(self):
        cli = self.getCLIInstance()
        cli.execute("pool-dynamic-memory-control-enable")
        self.dmcEnabled = True

    def disableDMC(self):
        cli = self.getCLIInstance()
        cli.execute("pool-dynamic-memory-control-disable")
        self.dmcEnabled = False

    def associateDVS(self, controller):
        self.master.associateDVS(controller)

    def disassociateDVS(self):
        self.master.disassociateDVS()

    def enableCaching(self):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getUUID()))
        cli.execute("pool-enable-local-storage-caching", string.join(args))

    def disableCaching(self):
        cli = self.getCLIInstance()
        args = []
        args.append("uuid=%s" % (self.getUUID()))
        cli.execute("pool-disable-local-storage-caching", string.join(args))

    def createVMPP(self, name, type, frequency, pdict={}):
        # Unfortunately, python doesn't accept params name like xxx-xxxx,
        # We should use "**kw" rather than "pdict"
        cli = self.getCLIInstance()
        args = []
        args.append("name-label=\"%s\"" % str(name).replace('"', '\\"'))
        args.append("backup-type=%s" % type)
        args.append("backup-frequency=%s" % frequency)
        for key,val in pdict.iteritems():
            args.append("%s=\"%s\"" % (key, str(val).replace('"', '\\"')))
        uuid = cli.execute("vmpp-create", args=' '.join(args)).strip()
        return uuid

    def listVMPP(self, pdict={}):
        args = []
        for key,val in pdict.iteritems():
            args.append("%s=\"%s\"" % (key, str(val).replace('"', '\\"')))
        result = self.master.minimalList("vmpp-list", args=' '.join(args))
        return result

    def deleteVMPP(self, vmpp=None, auto=False):
        cli = self.getCLIInstance()
        command = "vmpp-destroy"
        vmpps = vmpp and [vmpp] or self.listVMPP()
        for vuuid in vmpps:
            if auto:
                for vm in self.getVMPPConf(vmpp=vuuid)['VMs']:
                    self.master.genParamClear("vm", vm, "protection-policy")
            cli.execute(command, args="uuid=%s" % vuuid)

    def getVMPPConf(self, vmpp=None, pdict={}):
        if vmpp:
            result = self.master.parseConf("vmpp-param-list",
                                           args="uuid=%s" % vmpp)
        else:
            command = "vmpp-list"
            args = []
            for key,val in pdict.iteritems():
                args.append("%s=\"%s\"" % (key,str(val).replace('"', '\\"')))
            result = self.master.parseConfMulti(command, args=' '.join(args),
                                                index="uuid")
        return result

    def getVMPPParam(self, vmpp, param, pkey=None):
        if pkey is None:
            params = param.split(':', 1)
            param = params[0]
            pkey = len(params) > 1 and params[1] or pkey
        return self.master.genParamGet("vmpp", vmpp, param, pkey=pkey)

    def setVMPPParam(self, vmpp, param, value, pkey=None):
        if pkey is None:
            params = param.split(':', 1)
            param = params[0]
            pkey = len(params) > 1 and params[1] or pkey
        self.master.genParamSet("vmpp", vmpp, param, value, pkey=pkey)

    def getVMPPAlerts(self, vmpp, hours_from_now=None):
        session = self.getAPISession(secure=False)
        try:
            vmpp_ref = session.xenapi.VMPP.get_by_uuid(vmpp)
            if not hours_from_now:
                alerts = session.xenapi.VMPP.get_recent_alerts(vmpp_ref)
            else:
                alerts = session.xenapi.VMPP.get_alerts(vmpp_ref,
                                                        str(hours_from_now))
            allist = []
            for alert in alerts:
                aldom = xml.dom.minidom.parseString(alert).documentElement
                aldict = dict(map(lambda c: (c.tagName,
                                             (c.firstChild.nodeType == \
                                              c.firstChild.TEXT_NODE)
                                             and c.firstChild.data.strip()
                                             or dict(map(lambda n: (n.tagName,
                                                                    n.firstChild.data.strip()),
                                                         c.childNodes))),
                                  aldom.childNodes))
                allist.append(aldict)
            allist.sort(key=lambda e: e['time'], reverse=True)
            return allist
        finally:
            session.logoutAPISession()

    def upgrade(self, newVersion=None, rolling=False, poolUpgrade=None):
        if poolUpgrade is None:
            return Pool.upgrade(self, newVersion, rolling)
        else: 
            return poolUpgrade.doUpdate()

    def verifyRollingPoolUpgradeInProgress(self, expected=True):
        result = self.getPoolParam("other-config")
        if ("rolling_upgrade_in_progress: true" in result) != expected:
            xenrt.TEC().logverbose("RPU Mode is expected: %s, "\
                                   "other-config: %s" % (expected, result))
            raise xenrt.XRTFailure("RPU mode error")

    def isConfiguredForCC(self):
        return all(map(lambda h: h.isConfiguredForCC(), self.getHosts()))

    def configureForCC(self):
        for h in self.getHosts():
            h.configureForCC()

    def isSSLVerificationEnabled(self):
        return all(map(lambda h: h.isSSLVerificationEnabled(), self.getHosts()))

    def enableSSLVerification(self):
        for h in self.getHosts():
            h.enableSSLVerification()

    def disableSSLVerification(self):
        for h in self.getHosts():
            h.disableSSLVerification()

    def configureSSL(self, enableVerification=True):
        """Configure the pool with a CA certificate, and set up any hosts
           appropriately"""

        # Set up a CA to use
        self.ca = xenrt.sslutils.CertificateAuthority()

        # Install the CA certificate
        self.installCertificate(self.ca.certificate)

        # Set up a certificate for every host we know about
        for h in self.getHosts():
            pem = self.ca.createHostPEM(h, cn=h.getIP(), sanlist=["127.0.0.1"])
            h.installPEM(pem)
        if enableVerification and not self.isSSLVerificationEnabled():
            self.enableSSLVerification()

    def resetSSL(self):
        """Remove any SSL configurations from the pool"""
        self.disableSSLVerification()
        for h in self.getHosts():
            h.uninstallPEM(onlyIfOriginalExists=True)
        if self.ca:
            self.uninstallCertificate(self.ca.certificate)
            self.ca = None

    def installCertificate(self, cert):
        self.master.installCertificate(cert)
        self.synchroniseCertificates()

    def uninstallCertificate(self, cert):
        self.master.uninstallCertificate(cert)
        self.synchroniseCertificates()

    def isCertificateInstalled(self, cert):
        return self.master.isCertificateInstalled(cert)

    def synchroniseCertificates(self):
        cli = self.getCLIInstance()
        cli.execute("pool-certificate-sync")

#############################################################################

class BostonPool(MNRPool):
    """A pool of Boston Hosts"""
    
    def hostFactory(self):
        return xenrt.lib.xenserver.BostonHost
    
    def __init__(self, master):
        MNRPool.__init__(self, master)
        self.haSRTypes = ["lvmoiscsi", "lvmohba", "nfs"]

    def enableMultipathing(self, handle="dmp", mpp_rdac=False):
        
        hosts = self.getHosts()
        for h in hosts:
            h.enableMultipathing(handle, mpp_rdac)
            
        return
    
    def disableMultipathing(self, mpp_rdac=False):

        hosts = self.getHosts()
        for h in hosts:
            h.disableMultipathing(mpp_rdac)
            
        return

#############################################################################

class TampaPool(BostonPool):
    """A pool of Tampa hosts"""

    def hostFactory(self):
        return xenrt.lib.xenserver.TampaHost

#############################################################################

class ClearwaterPool(TampaPool):
    """A pool of Clearwater Hosts """

    def hostFactory(self):
        return xenrt.lib.xenserver.ClearwaterHost

    def checkLicenseState(self, edition):

        poolEdition = ""
        poolLicenseState = self.getPoolParam("license-state")
        
        info = re.search(r'edition:(.*);',poolLicenseState)
        if not info:
            raise xenrt.XRTFailure("Pool has no edition")
        else:    
            poolEdition = info.group(1).strip()       

        if not (edition == poolEdition):
            raise xenrt.XRTFailure("Pool edition is not similar to %s" % edition)

    def getNoOfSockets(self):

        socketCount = 0

        for h in self.getHosts():
            socketCount = socketCount + h.getNoOfSockets()

        if socketCount == 0:
            raise xenrt.XRTFailure("There is no socket with in the pool")
 
        return socketCount

    #This is a temp license function once clearwater and trunk will be in sync this will become "license" funtion
    def license(self, edition = "free", v6server = None, sku=None):

        cli = self.master.getCLIInstance()

        args = []

        if sku:
            edition = sku

        args.append("uuid=%s" % (self.getUUID()))
        args.append("edition=%s" % (edition))

        if v6server:
            args.append("license-server-address=%s" % (v6server.getAddress()))
            args.append("license-server-port=%s" % (v6server.getPort()))
        else:
            (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_LICENSE_SERVER").split(":")
            args.append("license-server-address=%s" % (addr))
            args.append("license-server-port=%s" % (port))

        cli.execute("pool-apply-edition", string.join(args))

        self.checkLicenseState(edition)

#############################################################################

class CreedencePool(ClearwaterPool):
    """A pool of Creedence Hosts """

    def hostFactory(self):
        return xenrt.lib.xenserver.CreedenceHost

    def license(self,v6server=None, sku="enterprise-per-socket"):

        args = []
        cli = self.master.getCLIInstance()
        args.append("uuid=%s" % (self.getUUID()))
        args.append("edition=%s" % (sku))

        if v6server:
            args.append("license-server-address=%s" % (v6server.getAddress()))
            args.append("license-server-port=%s" % (v6server.getPort()))
        else:
            if self.master.special.has_key('v6earlyrelease') and self.master.special['v6earlyrelease']:
                (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_PREVIEW_LICENSE_SERVER").split(":")
            else:
                (addr, port) = xenrt.TEC().lookup("DEFAULT_CITRIX_LICENSE_SERVER").split(":")
            args.append("license-server-address=%s" % (addr))
            args.append("license-server-port=%s" % (port))

        cli.execute("pool-apply-edition", string.join(args))

        self.checkLicenseState(sku)

    def licenseApply(self, v6server, licenseObj):
        self.license(v6server=v6server, sku=licenseObj.getEdition())

    def validLicenses(self, xenserverOnly=False):
        """
        option: xenserverOnly - return the SKUs for just XenServer
        """

        return self.master.validLicenses(xenserverOnly=xenserverOnly)

#############################################################################

class DundeePool(CreedencePool):

    def __init__(self, master):
        CreedencePool.__init__(self, master)
        self.haSRTypes = ["lvmoiscsi", "lvmohba", "nfs", "rawnfs"]

    def hostFactory(self):
        return xenrt.lib.xenserver.DundeeHost

#############################################################################

class RollingPoolUpdate(object):
    """This is the base class that defines the pool upgrade procedure"""

    def __init__(self,
                poolRef,
                newVersion=None,
                upgrade = True,
                applyAllHFXsBeforeApplyAction=False,
                vmActionIfHostRebootRequired='SHUTDOWN',
                preEvacuate=None,
                preReboot=None,
                skipApplyRequiredPatches=False):
        self.poolRef = poolRef
        self.newVersion = newVersion
        self.newPool = None
        self.upgrade = upgrade
        self.applyAllHFXsBeforeApplyAction = applyAllHFXsBeforeApplyAction
        self.vmActionIfHostRebootRequired = vmActionIfHostRebootRequired
        self.skipApplyRequiredPatches = skipApplyRequiredPatches
        self.guestsForPostHostReboot = []
        self.preEvacuate = preEvacuate
        self.preReboot = preReboot
        self.patch = None

    def doUpdateVariables(self):
        inputProductVersion = productVersionFromInputDir(xenrt.TEC().lookup("INPUTDIR"))

        if not self.newVersion:
            if self.upgrade:
                self.newVersion = inputProductVersion
            else:
                self.newVersion = self.poolRef.master.productVersion

        if self.newVersion == self.poolRef.master.productVersion:
            self.upgrade = False

        if self.upgrade:
            if self.newVersion == inputProductVersion:
                xenrt.TEC().setInputDir(None)
            else:
                newInputdir = productInputdirForVersion(self.newVersion)
                xenrt.TEC().setInputDir(newInputdir)

        if self.newVersion == inputProductVersion:
            self.patch = xenrt.TEC().lookup("THIS_HOTFIX", None)
        if not self.patch:
            self.patch = xenrt.TEC().lookup("THIS_HOTFIX_%s" % (self.newVersion.upper()), None)

    def doPreHostRebootVMAction(self, host):

        if self.preEvacuate:
            self.preEvacuate(host)

        if self.vmActionIfHostRebootRequired == "EVACUATE":
            host.evacuate()
            return

        self.guestsForPostHostReboot = []
        guests=[host.getGuest(g) for g in host.listGuests(running=True)]
        for g in guests:
            if self.vmActionIfHostRebootRequired == "SUSPEND" :
                g.suspend()
            elif self.vmActionIfHostRebootRequired == "SHUTDOWN":
                g.shutdown()
            self.guestsForPostHostReboot.append(g)
        
        if self.preReboot:
            self.preReboot(host)

    def doPostHostRebootVMAction(self, host):
        for g in self.guestsForPostHostReboot:
            if self.vmActionIfHostRebootRequired == "SUSPEND" :
                g.resume()
            elif self.vmActionIfHostRebootRequired == "SHUTDOWN":
                g.start()
        self.guestsForPostHostReboot = []

    def getApplyGuidance(self, host):
        guidance = host.minimalList("patch-list params=after-apply-guidance hosts:contains=%s" % host.uuid)
        if "restartHost" in guidance:
            return "restartHost"
        elif "restartXAPI" in guidance:
            return "restartXAPI"
        else:
            return "noAction"

    def doUpdateGuestObjects(self, host):
        # Upgrade each of this host's guest objects
        for oldg in host.guests.values():
            g = host.guestFactory()(oldg.getName())
            oldg.populateSubclass(g)
            host.guests[g.getName()] = g
            xenrt.TEC().registry.guestPut(g.getName(), g)

    def doUpdateHost(self, host):
        if self.upgrade:
            self.doPreHostRebootVMAction(host)
            newHost = host.upgrade(newVersion=self.newVersion)
            newHost.waitForEnabled(300, desc="Wait for upgraded host to become enabled")
            newHost.check()
            self.doUpdateGuestObjects(newHost)
            self.doPostHostRebootVMAction(newHost)
        else:
            newHost = host
            
        #Apply required hotfixes
        if self.applyAllHFXsBeforeApplyAction:
            if not self.skipApplyRequiredPatches:
                newHost.applyRequiredPatches(applyGuidance=False)
            if self.patch:
                newHost.applyPatch(xenrt.TEC().getFile(self.patch),applyGuidance=False)
            
            guidance = self.getApplyGuidance(newHost)
            log("Most significant apply guidance action: %s" % guidance)
            if guidance == "restartHost":
                self.doPreHostRebootVMAction(newHost)
            newHost.applyGuidance( guidance)
            if guidance == "restartHost":
                self.doPostHostRebootVMAction(newHost)
        else:
            if not self.skipApplyRequiredPatches:
                newHost.applyRequiredPatches(applyGuidance=True, applyGuidanceAfterEachPatch=True)
            if self.patch:
                newHost.applyPatch(xenrt.TEC().getFile(self.patch))

    def doUpdate(self):
        self.doUpdateVariables()

        self.licenseEdition = self.poolRef.master.getEdition()
        log("Current License Edition: %s" % (self.licenseEdition))

        log("RPU: Pre checks")
        self.preUpdateChecks()

        # Construct a new pool object
        self.newPool = xenrt.lib.xenserver.poolFactory(self.newVersion)(self.poolRef.master)
        self.poolRef.populateSubclass(self.newPool)
        
        log("RPU: Master update")
        self.preMasterUpdate()
        self.doUpdateHost(self.newPool.master)
        self.postMasterUpdate()

        for s in self.newPool.slaves:
            log("RPU: Slave update")
            self.preSlaveUpdate(self.newPool.slaves[s])
            self.doUpdateHost(self.newPool.slaves[s])
            self.postSlaveUpdate(self.newPool.slaves[s])

        if self.upgrade:
            log("Performing post pool update steps")
            self.newPool.master.postUpgrade()
            for slave in self.newPool.getSlaves():
                slave.postUpgrade()
 
        # Try and update the pool object in the registry (if present)
        try:
            xenrt.TEC().registry.poolReplace(self.poolRef, self.newPool)
        except:
            pass
        
        log("Update finished.")
        return self.newPool

    def preUpdateChecks(self):
        if self.poolRef.haEnabled:
            raise xenrt.XRTError("Cannot upgrade an HA enabled pool")

    def dumpPoolStatus(self):
        if self.newPool:
            xenrt.TEC().logverbose("New Pool Status:")
            pool = self.newPool
        else:
            xenrt.TEC().logverbose("Original Pool Status:")
            pool = self.poolRef 

        poolVMList = pool.master.parameterList('vm-list', ['power-state','resident-on','name-label'], 'is-control-domain=false')
        vmCount = 0

        xenrt.TEC().logverbose("Total number of VMs: %d" % (len(poolVMList)))

        nonRunningVms = filter(lambda x:x['power-state'] != 'running', poolVMList)
        xenrt.TEC().logverbose(" Non-running VMs (%d):" % (len(nonRunningVms)))
        map(lambda x:xenrt.TEC().logverbose("  VM Name: %s, Power State: %s" % (x['name-label'], x['power-state'])), nonRunningVms)
        vmCount += len(nonRunningVms)

        for h in pool.getHosts():
            runningVMs = filter(lambda x:x['resident-on'] == h.uuid and x['power-state'] == 'running', poolVMList)
            vmCount += len(runningVMs)
            if h == pool.master:
                xenrt.TEC().logverbose(" Master: %s VMs (%d):" % (h.getName(), len(runningVMs)))
            else:
                xenrt.TEC().logverbose(" Slave: %s VMs (%d):" % (h.getName(), len(runningVMs)))
           
            map(lambda x:xenrt.TEC().logverbose("  VM Name: %s" % (x['name-label'])), runningVMs) 

        if vmCount != len(poolVMList):
            xenrt.TEC().warning('VMs not accounted for during dumpPoolStatus: Total: %d, Accounted for: %d' % (len(poolVMList), vmCount))

    def _dumpNfsSRUsage(self, master):
        nfsSrUuids = master.minimalList(command='sr-list', args='type=nfs')
        if nfsSrUuids:
            pbdList = [master.parameterList(command='pbd-list', params=['device-config'], argsString='sr-uuid=%s host-uuid=%s currently-attached=true' % (x, master.uuid))[0] for x in nfsSrUuids]
            for pbd in pbdList:
                (path, server) = map(lambda x:x.split(':')[1].strip(), pbd['device-config'].split(';'))
                m = xenrt.rootops.MountNFS('%s:%s' % (server, path))
                mountPoint = m.getMount()
                diskInfo = xenrt.command('df -B GB %s | grep "%s"' % (mountPoint,mountPoint)).split()
                used = int(diskInfo[1].rstrip('GB'))
                available = int(diskInfo[2].rstrip('GB'))

                xenrt.TEC().logverbose('NFS DATA-df: Filesystem: %s, Used (GB): %d, Available (GB): %d' % (diskInfo[0].strip(), used, available))
                duInfo = xenrt.command('du -B GB %s | grep "%s"' % (mountPoint,mountPoint)).splitlines()
                used = int(duInfo[-1].split()[0].rstrip('GB'))
                mount = duInfo[-1].split()[1]
                xenrt.TEC().logverbose('NFS DATA-du: Mount: %s: Used (GB): %d' % (mount, used))

                m.unmount()

    def preMasterUpdate(self):
        log("RPU: Pre master update")
        self.newPool.verifyRollingPoolUpgradeInProgress(expected=False)
        xenrt.TEC().logverbose("Master %s original version: %s"\
         % (self.newPool.master.getName(), self.newPool.master.productRevision))
        self.dumpPoolStatus()
        self._dumpNfsSRUsage(self.newPool.master)

    def postMasterUpdate(self):
        log("RPU: Post master update")
        if len(self.newPool.slaves) != 0 and self.upgrade:
            self.newPool.verifyRollingPoolUpgradeInProgress(expected=True)
        xenrt.TEC().logverbose("Master %s new version: %s"\
         % (self.newPool.master.getName(), self.newPool.master.productRevision))

        self.dumpPoolStatus()
        self._dumpNfsSRUsage(self.newPool.master)
        # Wait (with a 5 minute timeout) until all slaves have checked in
        st = xenrt.util.timenow()
        timeout = 300
        xenrt.TEC().logverbose("Waiting %d seconds for all slaves to check "
                               " in..." % timeout)

        while True:
            if (xenrt.util.timenow() - st) > timeout:
                raise xenrt.XRTError("1 or more slaves did not check in "
                                     "within %d seconds" % timeout)

            allLive = True
            for slave in self.newPool.getSlaves():
                if slave.getHostParam("enabled") != "true" or \
                   slave.getHostParam("host-metrics-live") != "true":
                    allLive = False
                    break
            if allLive:
                xenrt.TEC().logverbose("...all slaves checked in")
                break
            xenrt.sleep(10)

    def preSlaveUpdate(self, slave):
        log("RPU: Pre slave update")
        if self.upgrade:
            self.newPool.verifyRollingPoolUpgradeInProgress(expected=True)
        xenrt.TEC().logverbose("Slave %s original version: %s"\
                               % (slave.getName(), slave.productRevision))
        self.dumpPoolStatus()
        self._dumpNfsSRUsage(self.newPool.master)

    def postSlaveUpdate(self, slave):
        log("RPU: Post slave update")
        xenrt.TEC().logverbose("Slave %s new version: %s"\
                               % (slave.getName(), slave.productRevision))
        self.dumpPoolStatus()
        self._dumpNfsSRUsage(self.newPool.master)


#############################################################################

class Tile(object):
    """A tile is a collection of VMs, optionally running workloads"""
    def __init__(self, host, sr, useWorkloads=True):
        self.host = host
        self.guests = []
        self.guestWorkloads = {}
        if xenrt.TEC().lookup("NO_TILE_WORKLOADS", False, boolean=True):
            self.useWorkloads = False        
        else:
            self.useWorkloads = useWorkloads
        self.sr = sr

    def install(self):
        # Current config is:
        # 2x w2k3eesp2 VMs
        # 2x RHEL 5.1 VMs    

        winWorkloads = [["Prime95"]]
        linuxWorkloads = [[],["LinuxSysbench"]]
        tileMemory = int(xenrt.TEC().lookup("TILE_MEMORY_MB", "2048")) # 2GB default

        templateVMs = None

        # Look for any existing templates
        if self.host.pool:
            object = self.host.pool
        else:
            object = self.host

        # Use a lock in case we're already installing templates
        object.tileLock.acquire()
        try:
            if object.tileTemplates.has_key(self.sr):
                templateVMs = object.tileTemplates[self.sr]
            else:
                templateVMs = self.createTemplates(self.sr)
        finally:
            object.tileLock.release()

        # Clone the templates
        gIndex = 0
        for g in templateVMs:
            newGuest = g.cloneVM(name="Tile-%s-%u" % (self.host.getName(),gIndex))
            gIndex += 1
            newGuest.host = self.host
            self.guests.append(newGuest)
            newGuest.memset(tileMemory)
            newGuest.start()

        # Sort out workloads        
        if self.useWorkloads:
            wi = 0
            li = 0
            for g in self.guests:
                if g.windows:
                    if len(winWorkloads) > wi:
                        self.guestWorkloads[g] = g.installWorkloads(winWorkloads[wi])
                        wi += 1
                else:
                    if len(linuxWorkloads) > li:
                        self.guestWorkloads[g] = g.installWorkloads(linuxWorkloads[li])
                        li += 1

        # Make sure they're shut down
        for g in self.guests:
            if g.getState() == "UP":
                g.shutdown()

    def createTemplates(self, sr):
        # Create the basic guest objects
        winDistro = self.host.lookup("TILE_WIN_DISTRO","w2k3eesp2")
        winGuests = 2
        linuxDistro = self.host.lookup("TILE_LINUX_DISTRO","rhel51")
        linuxGuests = 2
        tileInstalls = []
        templates = []
        templNo = 0

        isoname = xenrt.DEFAULT
        winG = self.host.guestFactory()("TileTemplate%u" % (templNo),
                                        self.host.getTemplate(winDistro),
                                        self.host)
        templNo += 1
        templates.append(winG)
        tileInstalls.append(_TileInstall(winG,self.host,{'distro':winDistro,
                                                         'isoname':isoname,
                                                         'sr':sr}))

        repository = xenrt.getLinuxRepo(linuxDistro, "x86-32", "HTTP")

        linG = self.host.guestFactory()("TileTemplate%u" % (templNo),
                                        self.host.getTemplate(linuxDistro),
                                        self.host)
        templNo += 1
        linG.arch = "x86-32"
        templates.append(linG)
        tileInstalls.append(_TileInstall(linG,self.host,{'distro':linuxDistro,
                                                         'repository':repository,
                                                         'sr':sr}))

        # Start the TileInstalls off
        for ti in tileInstalls:
            ti.start()

        # Give it some time to get going (this is so we catch exceptions
        # straight away)
        xenrt.sleep(30)

        # Wait for completion (don't worry about timeouts here, we let the
        # install methods deal with that...)
        for ti in tileInstalls:
            ti.join()
            if ti.exception:
                raise ti.exception

        # Install PV drivers for Windows guests
        for g in templates:
            if g.windows:
                g.installDrivers()

        # Tailor then shutdown the guests
        for g in templates:
            g.preCloneTailor()
            g.shutdown()

        # Clone to create the requisite number of each guest
        for i in range(winGuests - 1):
            templates.append(winG.cloneVM(name="TileTemplate%u" % (templNo)))
            templNo += 1
        for i in range(linuxGuests - 1):
            templates.append(linG.cloneVM(name="TileTemplate%u" % (templNo)))
            templNo += 1

        if self.host.pool:
            self.host.pool.tileTemplates[sr] = templates
        else:
            self.host.tileTemplates[sr] = templates

        return templates

    def start(self):
        for g in self.guests:
            g.start()

    def stop(self):
        for g in self.guests:
            g.shutdown()

    def check(self):
        for g in self.guests:
            # In case the guest has moved host
            try:
                g.findHost()
            except Exception, e:
                xenrt.TEC().logverbose("%s.findHost() exception: %s" %
                                       (g.getName(), str(e)))
            g.check()
            if self.useWorkloads and self.guestWorkloads.has_key(g):
                for w in self.guestWorkloads[g]:
                    # Verify workloads still running correctly
                    if not w.checkRunning():
                        if xenrt.TEC().lookup("TILE_WORKLOAD_WARN_ONLY", 
                                              False, boolean=True):
                            xenrt.TEC().warning("Workload %s no longer "
                                                "running" % (w.name))
                        else:
                            raise xenrt.XRTFailure("Workload %s no longer "
                                                   "running" % (w.name))

    def cleanup(self, force=False):
        for g in self.guests:
            g.shutdown(force=force)
            g.uninstall()

class _TileInstall(xenrt.XRTThread):
    """A class used to enable parallelism when installing tile VMs"""

    def __init__(self,guest,host,installArgs):
        self.guest = guest
        self.host = host
        self.installArgs = installArgs
        self.exception = None
        xenrt.XRTThread.__init__(self)

    def run(self):
        try:
            self.guest.install(self.host,**self.installArgs)
        except Exception, e:
            xenrt.TEC().logverbose("Exception while performing Tile guest "
                                   "install")
            traceback.print_exc(file=sys.stderr)
            self.exception = e


#############################################################################

class TransferVM(object):
    """ A class for TransferVM appliance. TransferVM is not a typical VM as
    xenrt VM object but some short-lived tooled VM launched for tranfer purpose
    and disappeared right after its usage. So the class TranferVM only exposes
    it usage API rather than the standard VM API.
    """

    def __init__(self, host):
        self.host = host
        self.command = "host-call-plugin host-uuid=%s plugin=transfer" \
                       % (self.host.getMyHostUUID())
    
    def expose(self, vdi_uuid,
               transfer_mode,               # http or bits or iscsi               
               read_only=False,                 
               use_ssl=False,               # only valid for http and bits
               ssl_version="TLSv1.2",       # enforce TLSv1.2, allow legacy SSL
               timeout_minutes=None,        # auto unexposed xxx minutes
                                            # after last TCP connection
               network_uuid=None,           # network uuid or default
                                            # management interface
               network_conf=None,           # dhcp by default or
                                            # {'ip','mask','gateway'}
               network_port=None,           # default port or specified
                                            # (only for http and bits)
               network_mac=None,            # specified or auto gen
               get_log=True,                # copy the logs into dom0 at unexpose
               vhd_blocks=None,
               vhd_uuid=None
               ):
        fn = "expose"        
        args = []
        args.append("vdi_uuid=%s" % vdi_uuid)
        args.append("transfer_mode=%s" % transfer_mode)
        args.append("read_only=%s" % read_only)
        args.append("use_ssl=%s" % use_ssl)
        if ssl_version != "TLSv1.2":
            args.append("ssl_version=%s" % ssl_version)
        if not network_mac:
            network_mac=xenrt.randomMAC()
        if timeout_minutes:
            args.append("timeout_minutes=%s" % timeout_minutes)
        args.append("network_uuid=%s" % (network_uuid or "management"))
        if network_conf:
            args += ["network_mode=manual",
                     "network_ip=%s" % network_conf['ip'],
                     "network_mask=%s" % network_conf['mask'],
                     "network_gateway=%s" % network_conf['gateway']]
        else:
            args.append("network_mode=dhcp")
        if network_port:
            args.append("network_port=%s" % network_port)
        if network_mac:
            args.append("network_mac=%s" % network_mac)
        if get_log:
            args.append("get_log=true")
        if vhd_blocks:
            args.append("vhd_blocks=%s" % vhd_blocks)
        if vhd_uuid: 
            args.append("vhd_uuid=%s" % vhd_uuid)

        args = map(lambda arg: "args:"+arg, args)
        args.insert(0, "fn=" + fn)
        cli = self.host.getCLIInstance()        
        return (cli.execute(self.command, " ".join(args), strip=True))

    def unexpose(self, record_handle=None, vdi_uuid=None):
        
        fn = "unexpose"
        args = []
        if record_handle:
            args.append("record_handle=" + record_handle)
        elif vdi_uuid:
            args.append("vdi_uuid=" + vdi_uuid)
        else:
            raise xenrt.XRTError("unexpose expects at least one of "
                                 "record_handle or vdi_uuid as arguments")
        args = map(lambda arg: "args:"+arg, args)        
        args.insert(0, "fn=" + fn)
        cli = self.host.getCLIInstance()
        return (cli.execute(self.command, " ".join(args), strip=True))

    @xenrt.irregularName
    def get_record(self, record_handle=None, vdi_uuid=None):

        fn = "get_record"
        args = []
        if record_handle:
            args.append("record_handle=" + record_handle)
        elif vdi_uuid:
            args.append("vdi_uuid=" + vdi_uuid)
        else:
            raise xenrt.XRTError("get_record expects at least onf of "
                                 "record_handle or vdi_uuid as arguments")
        args = map(lambda arg: "args:"+arg, args)        
        args.insert(0, "fn=" + fn)
        cli = self.host.getCLIInstance()
        res = cli.execute(self.command, " ".join(args))
        dom = xml.dom.minidom.parseString(res)
        attribs = dom.getElementsByTagName('transfer_record')[0].attributes        
        return (dict([(k, attribs[k].value.strip()) for k in attribs.keys()]))

    def cleanup(self):

        fn = "cleanup"
        cli = self.host.getCLIInstance()
        res = cli.execute(self.command, "fn=" + fn, strip=True)
        if res <> "OK":
            raise xenrt.XRTFailure("cleanup failed with feedback: %s" % res)

    def getBitmaps(self,vdi_uuid=None):
     
        fn = "get_bitmaps"
        args = []
        if vdi_uuid:
            args.append("leaf_vdi_uuids=" + str(vdi_uuid))
        else:
            raise xenrt.XRTError("get_bitmaps expects vdi_uuid as arguments")
        args = map(lambda arg: "args:"+arg,args)
        args.insert(0, "fn=" + fn)
        cli = self.host.getCLIInstance()
        return (cli.execute(self.command, " ".join(args), strip=True))

class IOvirt(object):
    """This class implements functionalities to test SR-IOV and pci pass thorough."""

    def __init__(self, host):
        self.host = host
        self.command = "host-call-plugin plugin=iovirt host-uuid=%s " \
            % (self.host.getMyHostUUID())

        self.vfs = {}
        
        self.lspci_list = None

    def getHost(self):
        if self.host.replaced:
            self.host = self.host.replaced
        return self.host        

    def enableIOMMU(self, restart_host=True):
        
        ret = self.getHost().execdom0("xe host-dmesg uuid=%s | grep iommu=1" % self.getHost().getMyHostUUID(), 
                                 retval="code")
        if ret == 0:
            return

        ret = self.getHost().execdom0('ls -l /etc/xapi.d/plugins/iovirt', retval='code')
        if ret != 0:
            raise xenrt.XRTError('iovirt plugin not found')
        
        cli = self.getHost().getCLIInstance()
        ret = cli.execute(self.command, "fn=enable_iommu", strip=True)

        if ret != "True":
            raise xenrt.XRTFailure("iovirt fn=enable_iommu failed: %s" % ret)
        
        if restart_host:
            self.getHost().reboot()
            self.getHost().waitForSSH(300, desc="host reboot after enabling iommu")
                
        return
    
    def __get_node_value__(self, dom, node_name):

        nodes = dom.getElementsByTagName(node_name)
        if len(nodes) > 0:
            node = nodes[0]
        else:
            return None
        
        node_val = node.firstChild.nodeValue.strip().encode('ascii')
        return (node_name, node_val)
            

    def __parse_xml_response__(self, res):
        """Returns a dict of vf assignment summary"""

        dom = xml.dom.minidom.parseString(res)
        vf_list = dom.getElementsByTagName('vf')
        vfs = {}

        for vf in vf_list:
            
            pciid = vf.getElementsByTagName('pciid')[0]
            pciid_val = pciid.firstChild.nodeValue.strip().encode('ascii')
            pci_info_list = []

            for node_name in ('device', 'vfnum', 'vlan', 'mac'):
                ret = self.__get_node_value__(vf, node_name)
                if ret is not None:
                    pci_info_list.append(ret)
            
            # if this vf is assigned to a vm, we will glean vm_uuid and index
            assigned_lst = vf.getElementsByTagName('assigned')
            if len(assigned_lst) > 0:
                assigned = assigned_lst[0]
                
                for node_name in ('vm', 'index'):
                    ret = self.__get_node_value__(assigned, node_name)
                    if ret is not None:
                        pci_info_list.append(ret)
                        
            vfs[pciid_val] = dict(pci_info_list)
            
        return vfs


    def __lspci_on_host__(self):
        
        """Returns a dict of {pciid => vendorid:deviceid}
           e.g. { 0000:00:04.0 => 10ec:8139 }
        """
        
        if self.lspci_list is not None:
            return

        self.lspci_list = {}

        res_lines = self.getHost().execdom0('lspci -D -n').splitlines()
        
        for line in res_lines:
            l = line.split()
            self.lspci_list[l[0]] = l[2]


    def queryVFs(self):
        
        cli = self.getHost().getCLIInstance()
        res = cli.execute(self.command, "fn=show_summary", strip=True)
        vfs = self.__parse_xml_response__(res)
        if len(vfs) == 0:
            raise xenrt.XRTFailure("SRIOV NIC doesn't have any VFs (???)")
        self.vfs.update(vfs)
        return


    def assignFreeVFToVM(self, vm_uuid, ethdev, vlan=None, mac=None):
        """Returns pciid of the vf"""

        args = "fn=assign_free_vf args:uuid=%s" % vm_uuid
        args += " args:ethdev=%s" % ethdev
        
        if vlan:
            args += " args:vlan=%s" % vlan
            
        if mac:
            args += " args:mac=%s" % mac

        cli = self.getHost().getCLIInstance()
        res = cli.execute(self.command, args, strip=True)
        vfs = self.__parse_xml_response__(res)
        self.vfs.update(vfs)
        
        return vfs.keys()[0]


    def unassignVF(self, vm_uuid, vfnum=None, ethdev=None, pciid=None, mac=None, index=None):

        cli = self.getHost().getCLIInstance()
        args = "fn=unassign_vf args:uuid=%s" % vm_uuid
        
        # do we have the index ?
        if index:
            args += " args:index=%s" % index
            res = cli.execute(self.command, args, strip=True)
            return

        # next we check for pciid
        if pciid:
            args += " args:pciid=%s" % pciid
            res = cli.execute(self.command, args, strip=True)
            return

        # next we check for mac
        if mac:
            args += " args:mac=%s" % mac
            res = cli.execute(self.command, args, strip=True)
            return
        
        # finally, it must be vfnum and ethdev
        if vfnum and ethdev:
            args += " args:ethdev=%s args:vf=%s" % (ethdev, vfnum)
            res = cli.execute(self.command, args, strip=True)
            return
        else:
            raise xenrt.XRTError("Insufficient arguments to fn=unassign_vf")
                    
    def addMacToVFsByIndex(self,vm_uuid, index=None, mac=None):
        cli = self.getHost().getCLIInstance()
        args = "fn=add_vf_mac args:uuid=%s" % vm_uuid
        if mac and index:
            args += " args:index=%s args:mac=%s" %  (index, mac)
        else:
            raise xenrt.XRTError("Insufficient arguements to fn=add_vf_mac")
        res = cli.execute(self.command, args, strip=True)
        dom = xml.dom.minidom.parseString(res)
        ret = self.__get_node_value__(dom,'result')
        if ret[1] == 'FAIL':
            xenrt.TEC().logverbose("FAIL message: %s" % self.__get_node_value__(dom,'message')[1])
            return [ret[1], self.__get_node_value__(dom,'message')[1]]
        return [ret[1]]
        
    def delMacToVFsByIndex(self,vm_uuid, index=None, mac=None):
        cli = self.getHost().getCLIInstance()
        args = "fn=del_vf_mac args:uuid=%s" % vm_uuid
        if mac and index:
            args += " args:index=%s args:mac=%s" %  (index, mac)
        else:
            raise xenrt.XRTError("Insufficient arguements to fn=del_vf_mac")
        cli.execute(self.command, args, strip=True)
        return 
        
    def changeMacOfVFsByIndex(self,vm_uuid, index=None, mac=None):
        cli = self.getHost().getCLIInstance()
        args = "fn=change_vf_mac args:uuid=%s" % vm_uuid
        if mac and index:
            args += " args:index=%s args:mac=%s" %  (index, mac)
        else:
            raise xenrt.XRTError("Insufficient arguements to fn=change_vf_mac")
        res = cli.execute(self.command, args, strip=True)
        dom = xml.dom.minidom.parseString(res)
        ret = self.__get_node_value__(dom,'result')
        return 


    def getAdditionalMacsFree(self, ethdev=None):
        cli = self.getHost().getCLIInstance()
        if ethdev:
            args = "fn=get_additional_macs_free args:ethdev=%s" % ethdev
        else:
            raise xenrt.XRTError("Must specify eth device by device, PIF or network.")
        res = cli.execute(self.command, args, strip=True)
        dom = xml.dom.minidom.parseString(res)
        n = self.__get_node_value__(dom,'macs')
        return n[1]
        
    def getAdditionalMacsTotal(self, ethdev=None):
        cli = self.getHost().getCLIInstance()
        if ethdev:
            args = "fn=get_additional_macs_total args:ethdev=%s" % ethdev
        else:
            raise xenrt.XRTError("Must specify eth device by device, PIF or network.")
        res = cli.execute(self.command, args, strip=True)
        dom = xml.dom.minidom.parseString(res)
        n = self.__get_node_value__(dom,'macs')
        return n[1]

    def addSriovFlags(self, guest=None, index=None, flag=None):
        cli = self.getHost().getCLIInstance()
        args = "fn=add_vf_flag args:uuid=%s" % guest.getUUID() 
        if index and flag:
            args += " args:index=%s args:flag=%s" % (index, flag)
        else:
            raise xenrt.XRTError("Need to specify VF Index and a flag")
    
    def delSriovFlag(self, guest=None, index=None, flag=None):
        cli = self.getHost().getCLIInstance()  
        args = "fn=del_vf_flag args:uuid=%s" % guest.getUUID()
        if index and flag:
            args += " args:index=%s args:flag=%s" % (index, flag)
        else:
            raise xenrt.XRTError("Need to specify VF Index and a flag")
  
    def __parse_get_vm_response__(self, res):
        
        dom = xml.dom.minidom.parseString(res)
        passthrough_list = dom.getElementsByTagName('passthrough')

        vfs_assigned_to_vm = {}
        for passthrough in passthrough_list:
            ret = self.__get_node_value__(passthrough, 'pciid')
            if ret is None:
                continue
            pciid = ret[1]
            tmp = []
            #for node_name in ('pttype',
            #                 'vendorid',
            #                 'deviceid',
            #                 'mac',
            #                 'vlan',
            #                 'device',
            #                 'vfnum',
            #                 'index'):

            #Implementing node_list so that it extracts all possible fields rather than explicitly mentioning them as 'vendorid','mac' etc 
            node_list=[str(i.nodeName) for i in passthrough.childNodes if i.nodeName !='#text'] #removing childNodes with junk text which has "#text" as notifiable pattern
            for node_name in node_list:
                ret = self.__get_node_value__(passthrough, node_name)
                if ret is not None:
                    tmp.append(ret)
            vfs_assigned_to_vm[pciid] = dict(tmp)
        return vfs_assigned_to_vm


    def getVMInfo(self, vm_uuid):
        
        cli = self.getHost().getCLIInstance()
        args = "fn=get_vm args:uuid=%s" % vm_uuid
        res = cli.execute(self.command, args, strip=True)
        pci_devs_assigned_to_vm = self.__parse_get_vm_response__(res)
        return pci_devs_assigned_to_vm

    
    def checkPCIDevsAssignedToVM(self, guest):
        
        pci_devs_assigned_to_vm = self.getVMInfo(guest.getUUID())
        self.__lspci_on_host__()

        pci_device_ids = {}
        
        for pciid in pci_devs_assigned_to_vm.keys():
            if pci_device_ids.has_key(self.lspci_list[pciid]):
                pci_device_ids[self.lspci_list[pciid]] += 1
            else:
                pci_device_ids[self.lspci_list[pciid]] = 1
            
        res_lines = guest.execguest('lspci -D -n').splitlines()
        
        pci_device_ids_from_vm = {}
        
        for device_id in [line.split()[2] for line in res_lines]:
            if pci_device_ids_from_vm.has_key(device_id):
                pci_device_ids_from_vm[device_id] += 1
            else:
                pci_device_ids_from_vm[device_id] = 1

        for device_id, number in pci_device_ids.items():
            
            if not pci_device_ids_from_vm.has_key(device_id):
                raise xenrt.XRTFailure("pciid (%s) not found in lspci listing on vm" % device_id)
            
            if pci_device_ids_from_vm[device_id] != number:
                raise xenrt.XRTFailure("Number of pciid (%s) found on vm (%s) doesn't match data from get_vm (%s)"
                                       % (device_id, 
                                          pci_device_ids_from_vm[device_id], 
                                          number))
        return 
                


    def getHWAddressFromVM(self, guest):

        res_lines = guest.execguest('ip link show').splitlines()

        even = lambda n : n % 2 == 0
    
        fst = [res_lines[i].split(':')[1].strip() 
               for i in range(len(res_lines)) 
               if even(i)]

        snd = [res_lines[i].split()[1].strip() 
               for i in range(len(res_lines))
               if not even(i)]

        return dict(zip(fst, snd))


    def getIPAddressFromVM(self, guest):
        
        eth_devs = self.getHWAddressFromVM(guest)

        ip_addrs = dict()

        if eth_devs.has_key('lo'):
            del eth_devs['lo']

        for eth_dev in eth_devs.keys():
            out = guest.execguest("ip addr show dev %s scope global | grep -e '^[[:space:]]\+inet\>' | head -n1 " % eth_dev).strip()
            if out == "":
                ip_addrs[eth_dev] = ""
            else:
                ip_addrs[eth_dev] = out.split()[1]
        return ip_addrs

    def getSRIOVEthDevices(self):

        if len(self.vfs) == 0:
            self.queryVFs()
        pifs = self.host.minimalList('pif-list carrier=false')
        broken_eths = set([self.host.genParamGet('pif', pif, 'device') for pif in pifs])
        all_sriov_eths = set([self.vfs[pciid]['device'] for pciid in self.vfs.keys()])
        usable_sriov_eths = all_sriov_eths - broken_eths
        return list(usable_sriov_eths)

    def getFreeVFs(self, ethdev):
        
        if len(self.vfs) == 0:
            self.queryVFs()
            
        fn = lambda x : x['device'] == ethdev and not x.has_key('vm') 
        
        return [pciid for pciid in self.vfs.keys() if fn(self.vfs[pciid]) ]
    
    
class Appliance(object):
    
    """This class implements appliance feature (implemented in Boston) """

    def __init__(self, host, name=None):
        
        if name is None:
            name = xenrt.randomApplianceName()

        assert host is not None
            
        self.name = name
        self.host = host
        self.uuid = None
        
        self.vms = []
        
    def create(self):
        
        if self.uuid is not None:
            return 
        
        cli = self.host.getCLIInstance()
        self.uuid = cli.execute('appliance-create', 'name-label=%s' % self.name, strip=True)
        
        return

    def addVM(self, guest):
        assert self.uuid is not None
        assert guest is not None
        
        cli = self.host.getCLIInstance()
        args = ['uuid=%s' % guest.getUUID(), 'appliance=%s' % self.uuid]
        cli.execute('vm-param-set', ' '.join(args))
        
        self.vms.append(guest)

        return
        
    def start(self):
        
        assert self.uuid is not None
        
        if not self.vms:
            xenrt.TEC().logverbose('Appliance (%s) has 0 VMs' % self.uuid)
            return

        cli = self.host.getCLIInstance()
        cli.execute('appliance-start', 'uuid=%s' % self.uuid)
        return

    def shutdown(self, force=False):
        
        assert self.uuid is not None

        if not self.vms:
            xenrt.TEC().logverbose('Appliance (%s) has 0 VMs' % self.uuid)
            return
        
        cli = self.host.getCLIInstance()
        args = 'uuid=%s' % self.uuid
        if force:
            args += ' force=true'
        cli.execute('appliance-shutdown', args)
        
        return 

def runOverdueCleanup(hostname):
    cleanUpFlagsDir = xenrt.TEC().lookup("CLEANUP_FLAGS_PATH") + '/' + hostname
    log("Checking for overdue cleanup...")
    if not os.path.exists(cleanUpFlagsDir):
        log("No overdue clean-up - %s not found." % cleanUpFlagsDir)
        return

    try:
        dirs = os.listdir(cleanUpFlagsDir)
        for category in dirs:
            log("Performing overdue clean-up of %s." % category )
            if category == "LACP":
                xenrt.lib.switch.lacpCleanUp(hostname)
            else:
                raise xenrt.XRTError(
                    "Clean-up not implemented for category '%s'" % category)
                
            if os.path.exists(cleanUpFlagsDir+'/'+category):
                raise xenrt.XRTError("CleanUp for '%s' failed" % category)
                
        # if clean-up succeeded, all directories should disappear
        dirs = os.listdir(cleanUpFlagsDir)
        if len(dirs) > 0:
            raise xenrt.XRTError(
                "CleanUp seems to have failed for host %s in following categories: %s."
                % (hostname, ",".join(dirs) ) )
        os.rmdir(cleanUpFlagsDir)        
    except Exception, e:
        # If clean-up failed, we want to borrow the server, in order to avoid further failures
        # and then raise an error.
        log("Exception during overdue clean-up operations for host %s:\n%s" % (hostname, e) )
        hours = 168
        c = [hostname]        
        c.append("-h")
        c.append("%u" % (hours))
        u = xenrt.TEC().lookup("USERID", None)
        if u:
            c.append("-u")
            c.append(u)
        xenrt.GEC().dbconnect.jobctrl("borrow", c)
        log("Borrowing host %s, in order to avoid further job runs on it." % hostname)
        log("Please review and fix the content of '%s' on the controller." % cleanUpFlagsDir)
        raise xenrt.XRTError("Clean-up failed. Please fix '%s' and then return host." % hostname)                               
 

