#
# XenRT: Test harness for Xen and the XenServer product family
#
# Harness and infrastructure maintenance testcases
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, re, string, os.path, urllib, traceback, time, shutil, stat, os, IPy
import xenrt
from xenrt.lazylog import step, comment, log, warning

class TCSiteStatus(xenrt.TestCase):
    """Record items of XenRT site status in result fields."""
    
    def run(self, arglist=[]):

        for var in ["XENRT_VERSION"]:
            value = xenrt.TEC().lookup(var, None)
            if value:
                self.tec.appresult("%s=%s" % (var, value))

class _TCSyncDir(xenrt.TestCase):
    """Synchronise local ISO exports with the central repository"""

    LOCAL_NFS_PATH = None
    MANAGED_FLAG = None
    SYNC_USER = None
    SYNC_HOST = None
    SYNC_RSH = None
    MASTER_DIR = None

    def run(self, arglist=[]):

        # If we do not have a ISO export then skip
        if not xenrt.TEC().lookup(self.LOCAL_NFS_PATH, None):
            self.tec.skip("This site does not have a %s" %
                          (self.LOCAL_NFS_PATH))
            return

        # If we do not manage the export (e.g. if we share a NFS server
        # with another site which performs the management) then
        # skip
        if not xenrt.TEC().lookup(self.MANAGED_FLAG,
                              False,
                              boolean=True):
            self.tec.skip("This site does not manage the export")
            return

        # Form the stem of the rsync command
        syncuser = xenrt.TEC().lookup(self.SYNC_USER, None)
        synchost = xenrt.TEC().lookup(self.SYNC_HOST, None)
        syncrsh = xenrt.TEC().lookup(self.SYNC_RSH, None)
        syncoptions = xenrt.TEC().lookup("RSYNC_OPTIONS", None)
        if not synchost:
            raise xenrt.XRTError("No %s configured" % (self.SYNC_HOST))
        self.rsynccmdstem = "rsync -avxl"
        if syncoptions:
            self.rsynccmdstem = self.rsynccmdstem + " %s" % syncoptions
        if syncrsh:
            # If we reference the SSH_PRIVATE_KEY_FILE then make a copy
            # of this with suitable permissions for ssh use
            sshkeyfile = xenrt.TEC().lookup("SSH_PRIVATE_KEY_FILE", None)
            if sshkeyfile and sshkeyfile in syncrsh:
                xenrt.TEC().logverbose("Making chmod 600 version of SSH key")
                sshkeyfile600 = xenrt.TEC().tempFile()
                shutil.copy(sshkeyfile, sshkeyfile600)
                shutil.copy("%s.pub" % (sshkeyfile),
                            "%s.pub" % (sshkeyfile600))
                os.chmod(sshkeyfile600, stat.S_IRWXU)
                os.chmod("%s.pub" % (sshkeyfile600), stat.S_IRWXU)
                syncrsh = syncrsh.replace(sshkeyfile, sshkeyfile600)
            self.rsynccmdstem = self.rsynccmdstem + " -e '%s'" % (syncrsh)
        if syncuser:
            self.rsynccmdstem = self.rsynccmdstem + " %s@%s:" % (syncuser,
                                                                 synchost)
        else:
            self.rsynccmdstem = self.rsynccmdstem + " %s:" % (synchost)

        nfspath = xenrt.TEC().lookup(self.LOCAL_NFS_PATH)
        masterpath = xenrt.TEC().lookup(self.MASTER_DIR, None)
        if not masterpath:
            raise xenrt.XRTError("No master path configured")
            
        # Create a mountpoint for ISOs
        if nfspath.startswith("%s:" %
                              (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"))):
            # It's a local controller export, shortcut by not mounting and
            # copying directly in.
            mount = None
            mountpoint = nfspath.split(":")[1]
        else:
            mount = xenrt.MountNFS(nfspath, retry=False)
            mountpoint = mount.getMount()
        try:
            # Perform the rsync
            rsynccmd = self.rsynccmdstem + masterpath + "/ " + \
                       mountpoint + "/"
            xenrt.TEC().logverbose(rsynccmd)
            xenrt.command("sudo %s" % rsynccmd, timeout=360000)
        finally:
            try:
                if mount:
                    mount.unmount()
            except:
                pass

class TCSyncLinuxISOs(_TCSyncDir):
    """Synchronise local Linux ISO exports with the central repository"""

    # Names of the site variables for this export
    LOCAL_NFS_PATH = "EXPORT_ISO_NFS_STATIC"
    MANAGED_FLAG = "MASTER_LINUX_ISOS_MANAGED"
    SYNC_USER = "MASTER_LINUX_ISOS_SYNC_USER"
    SYNC_HOST = "MASTER_LINUX_ISOS_SYNC_HOST"
    SYNC_RSH = "MASTER_LINUX_ISOS_SYNC_RSH"
    MASTER_DIR = "MASTER_LINUX_ISOS_DIR"

class TCSyncWindowsISOs(_TCSyncDir):
    """Synchronise local Windows ISO exports with the central repository"""

    # Names of the site variables for this export
    LOCAL_NFS_PATH = "EXPORT_ISO_NFS"
    MANAGED_FLAG = "MASTER_WINDOWS_ISOS_MANAGED"
    SYNC_USER = "MASTER_WINDOWS_ISOS_SYNC_USER"
    SYNC_HOST = "MASTER_WINDOWS_ISOS_SYNC_HOST"
    SYNC_RSH = "MASTER_WINDOWS_ISOS_SYNC_RSH"
    MASTER_DIR = "MASTER_WINDOWS_ISOS_DIR"

class TCSyncDistFiles(_TCSyncDir): 
    """Synchronise local distfiles with the central repository"""

    # Names of the site variables for this export
    LOCAL_NFS_PATH = "EXPORT_DISTFILES_NFS"
    MANAGED_FLAG = "MASTER_DISTFILES_MANAGED"
    SYNC_USER = "MASTER_DISTFILES_SYNC_USER"
    SYNC_HOST = "MASTER_DISTFILES_SYNC_HOST"
    SYNC_RSH = "MASTER_DISTFILES_SYNC_RSH"
    MASTER_DIR = "MASTER_DISTFILES_DIR"

class TCPrepareDellUpdate(xenrt.TestCase):
    def run(self, arglist=[]):
        host = self.getDefaultHost()
        host.execdom0("wget -q -O - http://linux.dell.com/repo/hardware/latest/bootstrap.cgi | bash")
        host.execdom0("yum install srvadmin-all -y", timeout=3600)
        host.execdom0("yum install dell_ft_install -y", timeout=3600)
        host.execdom0("yum install $(bootstrap_firmware) -y", timeout=3600)
        host.execdom0("inventory_firmware", timeout=3600)
        host.execdom0("update_firmware", timeout=3600)

class TCPerformDellUpdate(xenrt.TestCase):
    def run(self, arglist=[]):
        host = self.getDefaultHost()
        host.execdom0("update_firmware --yes", timeout=7200)
        host.reboot()


class TCSysInfo(xenrt.TestCase):
    
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
    
    def run(self, arglist=[]):
        cli = self.host.getCLIInstance()
        
        # 1. Memory

        memorystring = cli.execute("host-list params=memory-total")
        matches = re.search("memory-total.*?: (\d*)",memorystring)
        membytes = float(matches.group(1))
        memgigabytes = int(round(membytes/xenrt.GIGA))

        # 2. Disks

        diskinfo = []
        disks = []
        diskstring = self.host.execdom0("ls -l /dev/disk/by-path")
        for line in diskstring.splitlines():
            matches = re.search("(ide|scsi|sas)(.*)->\s\.\./\.\./(.*)", line)
            if matches != None:
                if re.search("part", matches.group(2)) == None:
                    disks.append(matches.group(3))
        for disk in disks:
            fdiskout = self.host.execdom0("fdisk -l /dev/%s" % disk)
            for line in fdiskout.splitlines():
                matches = re.search("Disk /dev/%s: (.*) GB" % disk, line)
                if matches != None:
                    diskinfo.append(int(round(float(matches.group(1)))))

        # 3. CPUs
        xecpustring = cli.execute("host-cpu-info")
        xecpulines = xecpustring.split("\n")
        cpucount = ""
        vendor = ""
        speed = ""
        flags = ""
        modelname = ""
        model = ""
        family = ""
        stepping = ""
        maskable = ""
        features = ""
        for xecpuline in xecpulines:
            matches = re.search("^\s*?cpu_count.*?: (.*)",xecpuline)
            if matches != None:
                cpucount = matches.group(1)
            matches = re.search("vendor\s*?: (.*)",xecpuline)
            if matches != None:
                vendor =  matches.group(1)
            matches = re.search("flags\s*?: (.*)",xecpuline)
            if matches != None:
                flags =  matches.group(1)
            matches = re.search("speed\s*?: (.*)",xecpuline)
            if matches != None:
                speed =  matches.group(1)
            matches = re.search("modelname\s*?: (.*)",xecpuline)
            if matches != None:
                modelname =  matches.group(1)
            matches = re.search("model\s*?: (.*)",xecpuline)
            if matches != None:
                model =  matches.group(1)
            matches = re.search("family\s*?: (.*)",xecpuline)
            if matches != None:
                family =  matches.group(1)
            matches = re.search("stepping\s*?: (.*)",xecpuline)
            if matches != None:
                stepping =  matches.group(1)
            matches = re.search("physical_features\s*?: (.*)",xecpuline)
            if matches != None:
                features =  matches.group(1)
            matches = re.search("maskable\s*?: (.*)",xecpuline)
            if matches != None:
                maskable =  matches.group(1)
        dmicpustring = self.host.execdom0("dmidecode -t 4")
        dmicpulines = dmicpustring.split("\n")

        socketcount = 0
        threadcount = 0
        corecount = 0

        for dmicpuline in dmicpulines:
            matches = re.search("Processor Information",dmicpuline) 
            if matches != None:
                socketcount = socketcount + 1
            matches = re.search("Core Count: (.*)",dmicpuline)
            if matches != None:
                corecount = corecount + int(matches.group(1))
            matches = re.search("Thread Count: (.*)",dmicpuline)
            if matches != None:
                threadcount = threadcount + int(matches.group(1))
        if int(cpucount) != threadcount: 
            xenrt.TEC().warning("CPU count from xe host-cpu-list did not match Thread count from DMI Decode, results cannot be trusted")

        if corecount == 0:
            corecount = int(cpucount) # Assume no hyperthreading if we can't work it out from dmidecode
        # 5. Network cards:

        pcistring = self.host.execdom0("lspci")
        pcilines = pcistring.split("\n")

        ethinfo = []

        for pciline in pcilines:
            matches = re.search("Ethernet", pciline)
            if matches != None:
                matches = re.search("Virtual Function", pciline)
                if matches == None:
                    ethinfo.append(pciline)
       
        # 6. Network interfaces

        nics = self.host.listSecondaryNICs()
        networks = {'NPRI' : 1}
        for nic in nics:
            net = self.host.getNICNetworkName(nic)
            if net != 'none':
                if net not in networks:
                    networks[net] = 0
                networks[net] = networks[net] + 1

            

        xenrt.TEC().appresult("CPU: Socket count: %d" % socketcount)
        xenrt.TEC().appresult("CPU: Core count: %d" % corecount)
        xenrt.TEC().appresult("CPU: Logical CPU count: %s" % cpucount)
        xenrt.TEC().appresult("CPU: Vendor: %s " % vendor)
        xenrt.TEC().appresult("CPU: Speed: %sMHz" % speed)
        xenrt.TEC().appresult("CPU: Model name: %s" % modelname)
        xenrt.TEC().appresult("CPU: Family - %s, Model - %s, Stepping - %s" % (family, model, stepping))
        xenrt.TEC().appresult("CPU: Flags: %s" % flags)
        xenrt.TEC().appresult("CPU: Features: %s" % features)
        xenrt.TEC().appresult("CPU: Features Maskable: %s" % maskable)
        xenrt.TEC().appresult("Memory: %dG" % memgigabytes)
        xenrt.TEC().appresult("Disks: %d" % len(diskinfo))
        resourcestring = "memory=%dG/sockets=%d/cores=%d/cpus=%s/disks=%d" % (memgigabytes, socketcount, corecount, cpucount, len(diskinfo))
        diskcount = 0
        for disk in diskinfo:
            diskcount = diskcount + 1
            xenrt.TEC().appresult("Disk %d: %dG" % (diskcount, disk))
            resourcestring = resourcestring + "/disk%d=%dG" % (diskcount, disk)
        xenrt.TEC().appresult("NICs: %d" % len(ethinfo))
        ethcount = 0
        for eth in ethinfo:
            ethcount = ethcount + 1
            xenrt.TEC().appresult("NIC %d: %s" %(ethcount, eth))

        for network in networks.iterkeys():
            xenrt.TEC().appresult("NICs on %s: %d" % (network, networks[network]))
            resourcestring = resourcestring + "/%s=%d" % (network, networks[network])
        xenrt.TEC().appresult("Resource string: %s" % resourcestring)
        dmistring = self.host.execdom0("dmidecode")
        filename = "%s/dmidecode.log" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        f.write(dmistring)
        f.close()
        
        filename = "%s/lspci.log" % (xenrt.TEC().getLogdir())
        f = file(filename, "w")
        f.write(pcistring)
        f.close()

class TCUnsupFlags(xenrt.TestCase):
    ALL_FLAGS = {
# XenServer
"unsup_6.0"     : { "productVersion":"Boston",      "isSetIfPass":False, "version":"/usr/groups/release/XenServer-6.x/XS-6.0.0/RTM-50762" },
"unsup_6.0.2"   : { "productVersion":"Sanibel",     "isSetIfPass":False, "version":"/usr/groups/release/XenServer-6.x/XS-6.0.2/RTM-53456" },
"unsup_6.1"     : { "productVersion":"Tampa",       "isSetIfPass":False, "version":"/usr/groups/release/XenServer-6.x/XS-6.1.0/RTM" },
"unsup_6.2"     : { "productVersion":"Clearwater",  "isSetIfPass":False, "version":"/usr/groups/release/XenServer-6.x/XS-6.2/RTM-70446" },
"unsup_6.5"     : { "productVersion":"Creedence",   "isSetIfPass":False, "version":"/usr/groups/release/XenServer-6.x/XS-6.5/RTM-90233" },
"unsup_7"       : { "productVersion":"Dundee",      "isSetIfPass":False, "version":"/usr/groups/build/trunk/latest" },
# ESXi VMware
"unsup_vmware55"    : { "productType" : "esx",      "productVersion":"5.5.0-update02",      "isSetIfPass": False },
"unsup_vmware51"    : { "productType" : "esx",      "productVersion":"5.1.0",               "isSetIfPass": False },
"unsup_vmware5"     : { "productType" : "esx",      "productVersion":"5.0.0.update01",      "isSetIfPass": False },
# HyperV
"unsup_ws12r2"      : { "productType":"hyperv",     "productVersion":"ws12r2-x64",          "isSetIfPass": False },
"unsup_hvs12r2"     : { "productType":"hyperv",     "productVersion":"hvs12r2-x64",         "isSetIfPass": False },
# KVM
"unsup_rhel63"      : { "productType":"kvm",        "productVersion":"rhel63_x86-64",       "isSetIfPass": False },
"unsup_rhel64"      : { "productType":"kvm",        "productVersion":"rhel64_x86-64",       "isSetIfPass": False },
"unsup_rhel65"      : { "productType":"kvm",        "productVersion":"rhel65_x86-64",       "isSetIfPass": False },
# Native Linux
"unsup_centos6x32"  : { "productType":"nativelinux", "productVersion":"centos6_x86-32",     "isSetIfPass": False },
"unsup_centos6"     : { "productType":"nativelinux", "productVersion":"centos6_x86-64",     "isSetIfPass": False },
"unsup_centos7"     : { "productType":"nativelinux", "productVersion":"centos7_x86-64",     "isSetIfPass": False },
"unsup_debian7x32"  : { "productType":"nativelinux", "productVersion":"debian70_x86-32",    "isSetIfPass": False },
"unsup_debian7"     : { "productType":"nativelinux", "productVersion":"debian70_x86-64",    "isSetIfPass": False },
"unsup_oel6x32"     : { "productType":"nativelinux", "productVersion":"oel6_x86-32",        "isSetIfPass": False },
"unsup_oel6"        : { "productType":"nativelinux", "productVersion":"oel6_x86-64",        "isSetIfPass": False },
"unsup_oel7"        : { "productType":"nativelinux", "productVersion":"oel7_x86-64",        "isSetIfPass": False },
"unsup_rhel6x32"    : { "productType":"nativelinux", "productVersion":"rhel6_x86-32",       "isSetIfPass": False },
"unsup_rhel6"       : { "productType":"nativelinux", "productVersion":"rhel6_x86-64",       "isSetIfPass": False },
"unsup_rhel7"       : { "productType":"nativelinux", "productVersion":"rhel7_x86-64",       "isSetIfPass": False }
    }

    def createTempSeq(self, productType=None, productVersion=None, version=None, **kargs):
        seqContent  = """<xenrt><prepare><host id="0" """
        seqContent += 'productType="%s" ' % productType if productType else ""
        seqContent += 'productVersion="%s" '% productVersion if productVersion else ""
        seqContent += 'version="%s" ' % version if version else ""
        seqContent += """/></prepare></xenrt>"""

        seqFile =xenrt.TEC().tempFile()
        with open(seqFile, 'w') as file:
            file.write(seqContent)
        log("Temp Seq file content : %s" % seqContent)
        return seqFile

    def doSequence(self, seqFile):
        seq = xenrt.TestSequence(seqFile)
        seq.doPreprepare()
        seq.doPrepare()

    def isPropAlreadySet(self, flag):
        return flag in xenrt.APIFactory().get_machine(self.machineName)['flags']

    def prepare(self, arglist):
        self.machineName = xenrt.PhysicalHost(xenrt.TEC().lookup("RESOURCE_HOST_0")).name
        self.flags = {}
        self.updateMachine = False
        self.updateMachineWithAutoFlaggerTag = ""

        args = self.parseArgsKeyValue(arglist)
        if "FLAGSTOCHECK" in args:
            [ self.flags.update({ flag:self.ALL_FLAGS[flag] }) for flag in args["FLAGSTOCHECK"].split(",") if flag in self.ALL_FLAGS]
        elif "AllFLAGS" in args:
            self.flags.update(self.ALL_FLAGS)
        if "UPDATEMACHINE" in args:
            self.updateMachine = True
        if "AUTOFLAGGERTAG" in args:
            self.updateMachineWithAutoFlaggerTag = args["AUTOFLAGGERTAG"]

    def run(self, arglist=[]):
        if self.updateMachineWithAutoFlaggerTag:
            params = xenrt.APIFactory().get_machine(self.machineName)['params']
            if "AUTOFLAGGERTAG" in params and params["AUTOFLAGGERTAG"] == self.updateMachineWithAutoFlaggerTag:
                comment("Machine %s has already been checked. Exiting." % self.machineName)
                return

        for flag,flagData in self.flags.iteritems():
            if "seqFile" in flagData:
                seqFile=flagData["seqFile"]
            elif "productType" in flagData or "productVersion" in flagData or "version" in flagData:
                seqFile = self.createTempSeq(**flagData)
            else:
                warning("Unimplemented")
            log("Using Temp Seq File : %s" % seqFile)

            passed = False
            try:
                self.doSequence(seqFile)
                passed = True
            except Exception, e:
                warning(str(e))

            if passed == flagData["isSetIfPass"] and not self.isPropAlreadySet(flag):
                comment("Adding flag '%s' to machine '%s'" % (flag, self.machineName))
                xenrt.APIFactory().update_machine(self.machineName, addflags=[flag])
            elif passed != flagData["isSetIfPass"] and self.isPropAlreadySet(flag):
                comment("Removing flag '%s' from machine '%s'" % (flag, self.machineName))
                xenrt.APIFactory().update_machine(self.machineName, delflags=[flag])
            else:
                comment("Machine '%s' %s flag '%s'" % (self.machineName,"is already having required" if self.isPropAlreadySet(flag) else "neither need nor has", flag))

        if self.updateMachineWithAutoFlaggerTag:
            comment("Updating Autoflagger tag for Machine '%s': '%s'" % (self.machineName, self.updateMachineWithAutoFlaggerTag))
            xenrt.APIFactory().update_machine(self.machineName, params={'AUTOFLAGGERTAG':self.updateMachineWithAutoFlaggerTag})

class BiosSetup(xenrt.TestCase):
    def run(self, arglist=[]):
        h = self.getDefaultHost()
        if not h:
            m = xenrt.PhysicalHost(xenrt.TEC().lookup("RESOURCE_HOST_0"))
            h = xenrt.GenericHost(m)
            h.findPassword()

        if "Dell" in h.execdom0("dmidecode -t 1"):
            if h.execdom0("test -e /opt/dell/toolkit/bin/syscfg", retval="code"):
                try:
                    h.execdom0("wget -q -O - http://linux.dell.com/repo/hardware/Linux_Repository_15.07.00/bootstrap.cgi | bash")
                except:
                    h.execdom0("rm -f /etc/yum.repos.d/Citrix.repo")
                    h.execdom0("rm -f /etc/yum.repos.d/CentOS-Base.repo")
                    h.execdom0("wget -q -O - http://linux.dell.com/repo/hardware/Linux_Repository_15.07.00/bootstrap.cgi | bash")
                h.execdom0("yum install -y syscfg")
                h.reboot()
            syscfg = h.execdom0("/opt/dell/toolkit/bin/syscfg")
            if xenrt.TEC().lookup("DELL_SERIAL_PORT_SWAP", False, boolean=True):
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --serialportaddrsel=alternate")
                except:
                    xenrt.TEC().warning("Failed to change serial port config")
            elif xenrt.TEC().lookup("DELL_SERIAL_PORT_DEFAULT", False, boolean=True):
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --serialportaddrsel=default")
                except:
                    xenrt.TEC().warning("Failed to change serial port config")
            if "--serialcomm" in syscfg:
                if h.lookup("SERIAL_CONSOLE_PORT", None) == "1":
                    serial = "com2cr"
                else:
                    serial = "com1cr"
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --serialcomm=%s" % serial)
                except:
                    xenrt.TEC().warning("Failed to configure serial output")
            if "--acpower" in syscfg:
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --acpower=on")
                except:
                    xenrt.TEC().warning("Failed to change AC power config")
            if "--f1f2promptonerror" in syscfg:
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --f1f2promptonerror=disable")
                except:
                    xenrt.TEC().warning("Failed to change F1/F2 prompt config")
            if "--sriov" in syscfg:
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --sriov=enable")
                except:
                    xenrt.TEC().warning("Failed to enable SRIOV")
            if "--inteltxt" in syscfg:
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --inteltxt=enable")
                except:
                    xenrt.TEC().warning("Failed to enable TXT")
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg tpm --tpmsecurity=onwithpbm")
                except:
                    xenrt.TEC().warning("Failed to enable TPM security")
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg tpm --tpmactivation=enabled")
                except:
                    xenrt.TEC().warning("Failed to activate TPM")
            if h.lookup("ASSET_TAG", None) and "--asset" in syscfg:
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --asset=%s" % (h.lookup("ASSET_TAG")))
                except:
                    xenrt.TEC().warning("Failed to enable TXT")
            if "--virtualization" in syscfg:
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --virtualization=enable")
                except:
                    xenrt.TEC().warning("Failed to enable TXT")
            if "--memtest" in syscfg:
                try:
                    h.execdom0("/opt/dell/toolkit/bin/syscfg --memtest=disable")
                except:
                    xenrt.TEC().warning("Failed to disable memtest")
                
        if h.lookup("BMC_ADDRESS", None):
            defaultDevice = h.execdom0("ip route show | grep default | awk '{print $5}'").strip()
            gw = h.execdom0("ip route show | grep default | awk '{print $3}'").strip()
            subnet = IPy.IP(h.execdom0("ip route show | grep -v default | grep ' %s ' | awk '{print $1}'" % defaultDevice).strip())

            bmcaddr = xenrt.getHostAddress(h.lookup("BMC_ADDRESS"))

            if not IPy.IP(bmcaddr) in subnet:
                raise xenrt.XRTError("BMC Address not on management network")

            h.execdom0("ipmitool -I open lan set 1 ipsrc static")
            h.execdom0("ipmitool -I open lan set 1 ipaddr %s" % bmcaddr)
            h.execdom0("ipmitool -I open lan set 1 netmask %s" % subnet.netmask().strNormal())
            h.execdom0("ipmitool -I open lan set 1 defgw ipaddr %s" % gw)
            h.execdom0("ipmitool -I open lan set 1 access on")
            try:
                h.execdom0("ipmitool -I open lan set 1 user")
            except:
                xenrt.TEC().logverbose("Warning: could not enable default user for IPMI")
            h.execdom0("ipmitool -I open delloem lcd set mode userdefined %s" % h.getName())
