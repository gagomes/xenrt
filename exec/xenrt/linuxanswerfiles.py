import sys, string, time, socket, re, os.path, os, shutil, random, sets, math
import traceback, xmlrpclib, crypt, glob, copy, httplib, urllib, mimetools
import xml.dom.minidom, threading, fnmatch, urlparse, libxml2
import xenrt, xenrt.ssh, xenrt.util, xenrt.rootops, xenrt.resources
import testcases.benchmarks.workloads
import bz2, simplejson
import IPy
import XenAPI
from xenrt.lazylog import log, warning


class RHELKickStartFile(object):
    def __init__(self,
                 distro,
                 maindisk,               
                 mounturl,                 
                 vifs=None,
                 host=None,
                 arch=None,
                 password=None,
                 ethdev=None,
                 ethmac=None,
                 vcpus=1,
                 memory=256,
                 bootDiskFS="ext4",
                 bootDiskSize=100,
                 options={},
                 installOn=xenrt.HypervisorType.native,
                 method="HTTP",
                 repository=None,
                 ethDevice="eth0",
                 pxe=True,
                 extraPackages=None,
                 ossVG=False):
        self.vcpus=vcpus
        self.memory=memory
        self.options=options
        self.ethdev=ethdev
        self.ethmac=ethmac
        self.pxe=pxe
        self.mainDisk = maindisk
        self.arch=arch
        self.distro = distro
        self.repository = repository
        # Workaround fedora server not having an "development-tools" group
        if self.distro.startswith("fedora"):
            self.repository = self.repository.replace("Server", "Everything")
        self.method = method
        self.installOn = installOn
        self.bootDiskFS = bootDiskFS
        self.bootDiskSize = bootDiskSize
        self.ethDevice=ethDevice
        self.extraPackages = extraPackages
        self.ossVG = ossVG
        self.password = password
        self.sleeppost=""
        self.rpmpost="#"
        self.host=host
        self.vifs=vifs
        self.mounturl=mounturl
        self.desktop = False
        
    def generate(self):
        return self._generateKS()

    def _generateKS(self):
        if self.distro.startswith("fedora"):
            kf=self._generateFedora()
        elif self.distro.startswith("rhel7") or self.distro.startswith("oel7") or self.distro.startswith("centos7") or self.distro.startswith("sl7"):
            kf=self._generate7()
        elif re.match("^(rhel|centos|oel|sl)[w]?6\d*",self.distro):
            kf=self._generate6()
        elif self.distro.startswith("rheld6"):
            self.desktop = True
            kf=self._generate6()
        elif self.distro.startswith("rhel5") or self.distro.startswith("oel5") or self.distro.startswith("centos5") or self.distro.startswith("sl5"):
            kf=self._generate5()
        else:
            kf=self._generate4()
        return kf

    def _key(self):
        pKey=xenrt.TEC().lookup(["PRODUCT_KEYS", self.distro], None)
        if pKey:
            return ("key %s" %(pKey))
        else:
            return ""
            
    def _package(self):
        if self.desktop:
            return "basic-desktop"
        else:
            return "development"

    def _password(self):
        if not self.password:
            self.password = xenrt.TEC().lookup("ROOT_PASSWORD")
        return crypt.crypt(self.password, 'Xa')

    def _url(self):
        if self.method == "HTTP":
            return "url --url %s" % self.repository
        elif self.method == "NFS":
            u = string.split(self.repository, ":")
            return "nfs --server %s --dir %s" % (u[0], u[1])
        elif self.method == "CDROM":
            return "cdrom"
        else:
            xenrt.TEC().warning("Unknown install method '%s'" % (self.method))

    def _timezone(self):
        if self.distro in ["rhel53", "centos53", "oel53"]:
            xenrt.TEC().logverbose("Using EXT-47 workaround")
            deftz = "Africa/Casablanca"
        else:
            deftz = "UTC"
        return xenrt.TEC().lookup("OPTION_CARBON_TZ", deftz)
        
    def _extra(self):
        extra=""
        if self.extraPackages:
            extra = string.join(self.extraPackages, "\n")   
        return extra
        
    def _kARG(self):
        karg=""
        if self.vcpus:
            karg = karg + " maxcpus =%s" % (self.vcpus)
        if self.memory:
            karg = karg + " mem=%sm" % (self.memory)
        return karg
        
    def _more(self):
        more=""
        if self.installOn==xenrt.HypervisorType.xen:   
           
            if self.pxe:
                more="reboot\n"
                self.sleeppost = "sleep 60\n"
            return more
        else:
            if self.options and self.options.has_key("ossvg"):
                ossvg = xenrt.TEC().lookup("OSS_VOLUME_GROUP")
                more = more + """part pv.01 --size=1 --grow --ondisk=%s
    volgroup %s pv.01
    """ % (self.mainDisk, ossvg)
            # Add anything extra
            kse = xenrt.TEC().lookup("KICKSTART_EXTRA", None)
            if kse:
                more += kse
                more += "\n"
            return more       
        
    def _netconfig(self,vifs,host):
        netconfig = ""
        if xenrt.TEC().lookup("CONFOTHERNET", False, boolean=True):
            gateway =self.host.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY"])
            for vif in self.vifs[1:]:
                n, b, m, i = vif
                netconfig += """
sed -i 's/ONBOOT=no/ONBOOT=yes/' /etc/sysconfig/network-scripts/ifcfg-%s
echo BOOTPROTO=dhcp >> /etc/sysconfig/network-scripts/ifcfg-%s
""" % (re.sub("nic", "eth", n), re.sub("nic", "eth", n))
                netconfig += """
echo GATEWAY=%s >> /etc/sysconfig/network
""" % (gateway)
        return netconfig
               
    def _generate7(self):
      

        out = """install
text
%s
unsupported_hardware
lang en_US.UTF-8
keyboard us
network --device %s --onboot yes --bootproto dhcp
rootpw --iscrypted %s
firewall --service==ssh
authconfig --enableshadow --enablemd5
selinux --disabled
timezone %s
bootloader --location=mbr --append="crashkernel=auto rhgb quiet"
zerombr
# The following is the partition information you requested
# Note that any partitions you deleted are not expressed
# here so unless you clear all partitions first, this is
# not guaranteed to work
clearpart --all --initlabel
part /boot --fstype=%s --size=%d --ondisk=%s
part pv.8 --grow --size=1 --ondisk=%s
volgroup VolGroup --pesize=32768 pv.8
logvol / --fstype=ext4 --name=lv_root --vgname=VolGroup --grow --size=1024 --maxsize=51200
logvol swap --name=lv_swap --vgname=VolGroup --grow --size=1008 --maxsize=2016
%s
%s

%%packages
@ core
@ development
@ console-internet
@ network-tools
bridge-utils
lvm2
e2fsprogs
nfs-utils
stunnel
net-tools
wget
time
%s
%%end
""" % (self._url(),
       self.ethDevice,
       self._password(),
       self._timezone(),
       self.bootDiskFS,
       self.bootDiskSize,
       self.mainDisk,
       self.mainDisk,
       self._key(),
       self._more(),
       self._extra()
       )

        if self.installOn == xenrt.HypervisorType.xen:
            postInstall = self._netconfig(self.vifs,self.host)
        else:
            postInstall = """
    CONFDIR=/etc/sysconfig/network-scripts
    MAC=`grep ^HWADDR ${CONFDIR}/ifcfg-%s | cut -d = -f 2 | tr '[:lower:]' '[:upper:]'`
    if [ "$MAC" != "%s" ]; then
        sed -i -e's/ONBOOT=yes/ONBOOT=no/' ${CONFDIR}/ifcfg-%s
        for c in ${CONFDIR}/ifcfg-eth*; do
            MAC=`grep ^HWADDR $c | cut -d = -f 2 | tr '[:lower:]' '[:upper:]'`
            if [ "$MAC" = "%s" ]; then
                sed -i -e's/ONBOOT=no/ONBOOT=yes/' $c
                echo 'BOOTPROTO=dhcp' >> $c
            fi
        done
    fi

    sed -i '/^serial/d' /boot/grub/grub.conf
    sed -i '/^terminal/d' /boot/grub/grub.conf

    echo "# CP-8436: Load mlx4_en whenever we try to load mlx4_core" > /etc/modprobe.d/mlx4.conf
    echo "install mlx4_core /sbin/modprobe --ignore-install mlx4_core && /sbin/modprobe mlx4_en" >> /etc/modprobe.d/mlx4.conf
""" % (self.ethdev, self.ethmac, self.ethdev, self.ethmac)

        out = out+ """
%%post
echo "# Flush firewall rules to avoid blocking iperf, synexec, etc." >> /etc/rc.local
echo "iptables -F" >> /etc/rc.local
echo "sleep 10" >> /etc/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}'` || true" >> /etc/rc.local
echo "sleep 10" >> /etc/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}'` || true " >> /etc/rc.local
echo "sleep 10" >> /etc/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}'` || true" >> /etc/rc.local
echo "sleep 10" >> /etc/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}'` || true" >> /etc/rc.local
echo "sleep 10" >> /etc/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}'` || true" >> /etc/rc.local
echo "sleep 10" >> /etc/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}'` || true" >> /etc/rc.local
chmod +x /etc/rc.d/rc.local
%s
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
%s
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s
%%end""" % (postInstall,self.mounturl, self.rpmpost, self.sleeppost)
        return out
                
    def _generateFedora(self):
      

        out = """install
text
%s
lang en_US.UTF-8
keyboard us
network --device %s --onboot yes --bootproto dhcp
rootpw --iscrypted %s
firewall --service==ssh
authconfig --enableshadow --enablemd5
selinux --disabled
timezone %s
bootloader --location=mbr --append="crashkernel=auto rhgb quiet"
zerombr
# The following is the partition information you requested
# Note that any partitions you deleted are not expressed
# here so unless you clear all partitions first, this is
# not guaranteed to work
clearpart --all --initlabel
part /boot --fstype=%s --size=%d --ondisk=%s
part pv.8 --grow --size=1 --ondisk=%s --maxsize=20000
volgroup VolGroup --pesize=32768 pv.8
logvol / --fstype=ext4 --name=lv_root --vgname=VolGroup --grow --size=1024 --maxsize=51200
logvol swap --name=lv_swap --vgname=VolGroup --grow --size=1008 --maxsize=2016
%s
%s

%%packages
@ core
@ development-tools
@ standard
bridge-utils
lvm2
e2fsprogs
nfs-utils
stunnel
net-tools
wget
time
%s
%%end
""" % (self._url(),
       self.ethDevice,
       self._password(),
       self._timezone(),
       self.bootDiskFS,
       self.bootDiskSize,
       self.mainDisk,
       self.mainDisk,
       self._key(),
       self._more(),
       self._extra()
       )

        if self.installOn == xenrt.HypervisorType.xen:
            postInstall = self._netconfig(self.vifs,self.host)
        else:
            postInstall = """
    CONFDIR=/etc/sysconfig/network-scripts
    MAC=`grep ^HWADDR ${CONFDIR}/ifcfg-%s | cut -d = -f 2 | tr '[:lower:]' '[:upper:]'`
    if [ "$MAC" != "%s" ]; then
        sed -i -e's/ONBOOT=yes/ONBOOT=no/' ${CONFDIR}/ifcfg-%s
        for c in ${CONFDIR}/ifcfg-eth*; do
            MAC=`grep ^HWADDR $c | cut -d = -f 2 | tr '[:lower:]' '[:upper:]'`
            if [ "$MAC" = "%s" ]; then
                sed -i -e's/ONBOOT=no/ONBOOT=yes/' $c
                echo 'BOOTPROTO=dhcp' >> $c
            fi
        done
    fi

    sed -i '/^serial/d' /boot/grub/grub.conf
    sed -i '/^terminal/d' /boot/grub/grub.conf

    echo "# CP-8436: Load mlx4_en whenever we try to load mlx4_core" > /etc/modprobe.d/mlx4.conf
    echo "install mlx4_core /sbin/modprobe --ignore-install mlx4_core && /sbin/modprobe mlx4_en" >> /etc/modprobe.d/mlx4.conf
""" % (self.ethdev, self.ethmac, self.ethdev, self.ethmac)

        out = out+ """
%%post
echo "#!/bin/bash" >> /etc/rc.d/rc.local
echo "# Flush firewall rules to avoid blocking iperf, synexec, etc." >> /etc/rc.d/rc.local
echo "iptables -F" >> /etc/rc.d/rc.local
echo "sleep 10" >> /etc/rc.d/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}' | head -1` || true" >> /etc/rc.d/rc.local
echo "sleep 10" >> /etc/rc.d/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}' | head -1` || true" >> /etc/rc.d/rc.local
echo "sleep 10" >> /etc/rc.d/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}' | head -1` || true" >> /etc/rc.d/rc.local
echo "sleep 10" >> /etc/rc.d/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}' | head -1` || true" >> /etc/rc.d/rc.local
echo "sleep 10" >> /etc/rc.d/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}' | head -1` || true" >> /etc/rc.d/rc.local
echo "sleep 10" >> /etc/rc.d/rc.local
echo "ping -c 1 `ip route show | grep default | awk '{print $3}' | head -1` || true" >> /etc/rc.d/rc.local
chmod +x /etc/rc.d/rc.local
%s
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
%s
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s
%%end""" % (postInstall,self.mounturl, self.rpmpost, self.sleeppost)
        return out
                
    def _generate6(self):
      
        # RHEL 6.4+ allows use of the unsupported_hardware command, which means we'll be able to run it on newer hardware

        if not self.distro in ['rhel6', 'rhel61', 'rhel62', 'rhel63',
                               'centos6', 'centos61', 'centos62', 'centos63',
                               'oel6', 'oel61', 'oel62', 'oel63']:
            unsuphw = "unsupported_hardware"
        else:
            unsuphw = ""

        out = """install
text
%s
%s
lang en_US.UTF-8
keyboard us
network --device %s --onboot yes --bootproto dhcp
rootpw --iscrypted %s
firewall --service==ssh
authconfig --enableshadow --enablemd5
selinux --disabled
timezone %s
bootloader --location=mbr --append="crashkernel=auto rhgb quiet"
zerombr
# The following is the partition information you requested
# Note that any partitions you deleted are not expressed
# here so unless you clear all partitions first, this is
# not guaranteed to work
clearpart --all --initlabel
part /boot --fstype=%s --size=%d --ondisk=%s
part pv.8 --grow --size=1 --ondisk=%s --maxsize=12000 
volgroup VolGroup --pesize=32768 pv.8
logvol / --fstype=ext4 --name=lv_root --vgname=VolGroup --grow --size=1024 --maxsize=51200
logvol swap --name=lv_swap --vgname=VolGroup --grow --size=1008 --maxsize=2016
%s
%s

%%packages
@ core
@ %s
@ console-internet
@ network-tools
bridge-utils
lvm2
grub
e2fsprogs
nfs-utils
stunnel
%s
""" % (self._url(),
       unsuphw,
       self.ethDevice,
       self._password(),
       self._timezone(),
       self.bootDiskFS,
       self.bootDiskSize,
       self.mainDisk,
       self.mainDisk,
       self._key(),
       self._more(),
       self._package(),
       self._extra()
       )

        if self.installOn == xenrt.HypervisorType.xen:
            postInstall = self._netconfig(self.vifs,self.host)
        else:
            postInstall = """
    CONFDIR=/etc/sysconfig/network-scripts
    MAC=`grep ^HWADDR ${CONFDIR}/ifcfg-%s | cut -d = -f 2 | tr '[:lower:]' '[:upper:]'`
    if [ "$MAC" != "%s" ]; then
        sed -i -e's/ONBOOT=yes/ONBOOT=no/' ${CONFDIR}/ifcfg-%s
        for c in ${CONFDIR}/ifcfg-eth*; do
            MAC=`grep ^HWADDR $c | cut -d = -f 2 | tr '[:lower:]' '[:upper:]'`
            if [ "$MAC" = "%s" ]; then
                sed -i -e's/ONBOOT=no/ONBOOT=yes/' $c
                echo 'BOOTPROTO=dhcp' >> $c
            fi
        done
    fi

    sed -i '/^serial/d' /boot/grub/grub.conf
    sed -i '/^terminal/d' /boot/grub/grub.conf

    echo "# CP-8436: Load mlx4_en whenever we try to load mlx4_core" > /etc/modprobe.d/mlx4.conf
    echo "install mlx4_core /sbin/modprobe --ignore-install mlx4_core && /sbin/modprobe mlx4_en" >> /etc/modprobe.d/mlx4.conf
""" % (self.ethdev, self.ethmac, self.ethdev, self.ethmac)

        out = out+ """
%%post
%s
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
%s
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s""" % (postInstall,self.mounturl, self.rpmpost, self.sleeppost)
        return out
        
                    
    def _generate4(self):
        
        out = """install
text
%s
lang en_US.UTF-8
langsupport --default=en_US.UTF-8 en_US.UTF-8
keyboard us
network --device %s --bootproto dhcp
rootpw --iscrypted %s
firewall --enabled --ssh 
selinux --disabled
authconfig --enableshadow --enablemd5
timezone %s
bootloader --location=mbr --append="console=ttyS0,115200n8"
# The following is the partition information you requested
# Note that any partitions you deleted are not expressed
# here so unless you clear all partitions first, this is
# not guaranteed to work
clearpart --linux --all --initlabel
part /boot --fstype "ext3" --size=%d --ondisk=%s
part pv.8 --size=0 --grow --ondisk=%s --maxsize=12000
volgroup VolGroup00 --pesize=32768 pv.8
logvol / --fstype ext3 --name=LogVol00 --vgname=VolGroup00 --size=1024 --grow
logvol swap --fstype swap --name=LogVol01 --vgname=VolGroup00 --size=1000
%s
%s

%%packages
@ admin-tools
@ text-internet
@ dialup
@ server-cfg
@ development-tools
@ development-libs
bridge-utils
lvm2
grub
e2fsprogs
%s
""" % (self._url(),
       self.ethDevice,
       self._password(),
       self._timezone(),
       self.bootDiskSize,
       self.mainDisk,
       self.mainDisk,
       self._key(),
       self._more(),
       self._extra()
       )
       
        out = out+ """
%%post
%s
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
%s
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s""" % (self._netconfig(self.vifs,self.host),self.mounturl, self.rpmpost, self.sleeppost)
        return out

    def _generate5(self):
        
        out = """install
text
%s
key --skip
lang en_US.UTF-8
langsupport --default=en_US.UTF-8 en_US.UTF-8
keyboard us
network --device %s --bootproto dhcp
rootpw --iscrypted %s
firewall --enabled --ssh 
selinux --disabled
authconfig --enableshadow --enablemd5
timezone %s
bootloader --location=mbr --append="console=ttyS0,115200n8"
# The following is the partition information you requested
# Note that any partitions you deleted are not expressed
# here so unless you clear all partitions first, this is
# not guaranteed to work
clearpart --linux --all --initlabel
part /boot --fstype "ext3" --size=%d --ondisk=%s
part pv.8 --size=0 --grow --ondisk=%s --maxsize=12000
volgroup VolGroup00 --pesize=32768 pv.8
logvol / --fstype ext3 --name=LogVol00 --vgname=VolGroup00 --size=1024 --grow
logvol swap --fstype swap --name=LogVol01 --vgname=VolGroup00 --size=1000
%s
%s

%%packages
@ admin-tools
@ text-internet
@ dialup
@ server-cfg
@ development-tools
@ development-libs
bridge-utils
lvm2
grub
e2fsprogs
%s
""" % (self._url(),
       self.ethDevice,
       self._password(),
       self._timezone(),
       self.bootDiskSize,
       self.mainDisk,
       self.mainDisk,
       self._key(),
       self._more(),
       self._extra()
       )
       
        out = out+ """
%%post
%s
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
%s
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s""" % (self._netconfig(self.vifs,self.host),self.mounturl, self.rpmpost, self.sleeppost)
        return out
        
        
class SLESAutoyastFile(object):

    def __init__(self,
                 distro,
                 signalDir,
                 maindisk,
                 installOn=xenrt.HypervisorType.native,
                 pxe=False,
                 password=None,
                 method="HTTP",
                 ethDevice="eth0",
                 extraPackages=None,
                 kickStartExtra=None,
                 bootDiskSize=None,
                 ossVG=False,
                 rebootAfterInstall = True):
        self.mainDisk = maindisk
        self.pxe=pxe
        self.password=password
        self.distro = distro
        self.postinstall=""
        self.method = method
        self.installOn = installOn
        self.ethDevice=ethDevice
        self.extraPackages = extraPackages
        self.kickStartExtra = kickStartExtra
        self.ossVG = ossVG
        self.signalDir=signalDir
        self.bootDiskSize=bootDiskSize
        self.rebootAfterInstall = rebootAfterInstall
    
    def _password(self):
        if not self.password:
            self.password=xenrt.TEC().lookup("ROOT_PASSWORD")
        return self.password
    def _rebootAfterInstall(self):
        if self.rebootAfterInstall:
            return "/sbin/reboot"
        else:
            return ""
    def _timezone(self):
        deftz="UTC"
        return xenrt.TEC().lookup("OPTION_CARBON_TZ", deftz)
        
    def _bootDiskSize(self):
        return xenrt.TEC().lookup("BOOTDISKSIZE", "100")
        
    def _postInstall(self):
        return self.postinstall
    
    def generate(self):
        if self.installOn==xenrt.HypervisorType.xen:
            ay=self._generateAY()
        else:
            ay=self._generateNativeAY()
        return ay 

    def _package(self):        
        if self.distro.startswith("sles12"):
            return "<pattern>base</pattern>"
        return ""
 
    def _generateNativeAY(self):
        if re.search(r"sles101",self.distro) or re.search(r"sles102",self.distro):
            kf=self._generateNativeSLES101()                
        else:
            kf=self._generateNative()
        
    def _generateAY(self):
        if self.distro.startswith("sles11"):
            kf=self._generateSLES11x()
        elif re.search(r"^sle.12",self.distro):
            kf=self._generateSLES12()
        elif self.distro.startswith("sles94"):
            kf=self._generateSLES94()
        elif self.distro.startswith("sled11"):
            kf=self._generateSLED11()
        else:
            kf=self._generateStandard()
            
        if not self.pxe:
            kf = string.replace(kf, "/dev/hda", "/dev/xvda")
            kf = string.replace(kf, "bootloader", "bootloaderXXX")
            
        return kf
  
    def _generateNativeSLES101(self):
        ks="""<?xml version="1.0"?>
<!DOCTYPE profile SYSTEM "/usr/share/autoinstall/dtd/profile.dtd">
<profile xmlns="http://www.suse.com/1.0/yast2ns" xmlns:config="http://www.suse.com/1.0/configns">
  <configure>
    <networking>
      <dns>
        <dhcp_hostname config:type="boolean">false</dhcp_hostname>
        <dhcp_resolv config:type="boolean">false</dhcp_resolv>
      </dns>
      <routing>
        <ip_forward config:type="boolean">false</ip_forward>
      </routing>
      <interfaces config:type="list">
        <interface>
          <bootproto>dhcp</bootproto>
          <device>%s</device>        
          <startmode>onboot</startmode>
        </interface>
      </interfaces>
    </networking>
    <printer>
      <cups_installation config:type="symbol">server</cups_installation>
      <default></default>
      <printcap config:type="list"/>
      <server_hostname></server_hostname>
      <spooler>cups</spooler>
    </printer>
    <runlevel>
      <default>3</default>
    </runlevel>
    <security>
      <console_shutdown>reboot</console_shutdown>
      <cracklib_dict_path>/usr/lib/cracklib_dict</cracklib_dict_path>
      <cwd_in_root_path>no</cwd_in_root_path>
      <cwd_in_user_path>no</cwd_in_user_path>
      <displaymanager_remote_access>no</displaymanager_remote_access>
      <enable_sysrq>no</enable_sysrq>
      <fail_delay>3</fail_delay>
      <faillog_enab>yes</faillog_enab>
      <gid_max>60000</gid_max>
      <gid_min>1000</gid_min>
      <kdm_shutdown>auto</kdm_shutdown>
      <lastlog_enab>yes</lastlog_enab>
      <obscure_checks_enab>yes</obscure_checks_enab>
      <pass_max_days>99999</pass_max_days>
      <pass_max_len>8</pass_max_len>
      <pass_min_days>0</pass_min_days>
      <pass_min_len>5</pass_min_len>
      <pass_warn_age>7</pass_warn_age>
      <passwd_encryption>des</passwd_encryption>
      <passwd_use_cracklib>yes</passwd_use_cracklib>
      <permission_security>easy</permission_security>
      <run_updatedb_as>nobody</run_updatedb_as>
      <system_gid_max>499</system_gid_max>
      <system_gid_min>100</system_gid_min>
      <system_uid_max>499</system_uid_max>
      <system_uid_min>100</system_uid_min>
      <uid_max>60000</uid_max>
      <uid_min>1000</uid_min>
      <useradd_cmd>/usr/sbin/useradd.local</useradd_cmd>
      <userdel_postcmd>/usr/sbin/userdel-post.local</userdel_postcmd>
      <userdel_precmd>/usr/sbin/userdel-pre.local</userdel_precmd>
    </security>
    <sound>
      <configure_detected config:type="boolean">false</configure_detected>
      <modules_conf config:type="list"/>
      <rc_vars/>
      <volume_settings config:type="list"/>
    </sound>
    <users config:type="list">
      <user>
        <encrypted config:type="boolean">false</encrypted>
        <user_password>%s</user_password>
        <username>root</username>
      </user>
    </users>
    <scripts>
      <chroot-scripts config:type="list"/>      
      <post-scripts config:type="list"/>
      <pre-scripts config:type="list"/>      
      <init-scripts config:type="list">
        <script>
          <filename>post.sh</filename>
          <interpreter>shell</interpreter> 
          <source><![CDATA[
#!/bin/sh

mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
]]>
          </source>
        </script>
      </init-scripts>
    </scripts>
  </configure>
  <install>
    <bootloader>
      <activate config:type="boolean">true</activate>
      <device_map config:type="list">
        <device_map_entry>
          <firmware>hd0</firmware>
          <linux>/dev/%s</linux>
        </device_map_entry>
      </device_map>
      <global config:type="list">
        <global_entry>
          <key>color</key>
          <value>white/blue black/light-gray</value>
        </global_entry>
        <global_entry>
          <key>default</key>
          <value config:type="integer">0</value>
        </global_entry>
        <global_entry>
          <key>timeout</key>
          <value config:type="integer">8</value>
        </global_entry>
      </global>
      <loader_device>/dev/sda</loader_device>
      <loader_type>grub</loader_type>
      <location>mbr</location>
      <repl_mbr config:type="boolean">true</repl_mbr>
      <sections config:type="list">
        <section config:type="list">
          <section_entry>
            <key>title</key>
            <value>Linux</value>
          </section_entry>
          <section_entry>
            <key>root</key>
            <value>(hd0,0)</value>
          </section_entry>
          <section_entry>
            <key>kernel</key>
            <value>/boot/vmlinuz root=/dev/%s2 selinux=0 serial console=ttyS0,115200 load_ramdisk=1 splash=silent showopts elevator=cfq</value>
          </section_entry>
          <section_entry>
            <key>initrd</key>
            <value>/boot/initrd</value>
          </section_entry>
        </section>
      </sections>
    </bootloader>
    <general>
      <clock>
        <hwclock>localtime</hwclock>
        <timezone>%s</timezone>
      </clock>
      <keyboard>
        <keymap>english-uk</keymap>
      </keyboard>
      <language>en_GB</language>
      <mode>
        <confirm config:type="boolean">false</confirm>
        <forceboot config:type="boolean">false</forceboot>
      </mode>
      <mouse>
        <id>none</id>
      </mouse>
      <signature-handling>
        <accept_verification_failed config:type="boolean">true</accept_verification_failed>
        <accept_file_without_checksum config:type="boolean">true</accept_file_without_checksum> 
      </signature-handling>  
    </general>
    <partitioning config:type="list">
      <drive>
        <device>/dev/%s</device>
        <initialize config:type="boolean">false</initialize>
        <partitions config:type="list">
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/boot</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>%sM</size>
          </partition>
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>10G</size>
          </partition>
        </partitions>
        <use>all</use>
      </drive>
    </partitioning>
    <software>
      <patterns config:type="list">
        <pattern>base</pattern>
        <pattern>Basis-Devel</pattern>
      </patterns>
    </software>
  </install>
</profile>
""" % (self.ethDevice,
       self._password(),
       self.signalDir,
       self.mainDisk,
       self.mainDisk,
       self._timezone(),
       self.mainDisk,
       self.bootDiskSize
       )
        return ks

    def _generateNative(self):
        ks="""<?xml version="1.0"?>
<!DOCTYPE profile SYSTEM "/usr/share/autoinstall/dtd/profile.dtd">
<profile xmlns="http://www.suse.com/1.0/yast2ns" xmlns:config="http://www.suse.com/1.0/configns">
  <configure>
    <networking>
      <dns>
        <dhcp_hostname config:type="boolean">false</dhcp_hostname>
        <dhcp_resolv config:type="boolean">false</dhcp_resolv>
      </dns>
      <routing>
        <ip_forward config:type="boolean">false</ip_forward>
      </routing>
      <interfaces config:type="list">
        <interface>
          <bootproto>dhcp</bootproto>
          <device>%s</device>        
          <startmode>onboot</startmode>
        </interface>
      </interfaces>
    </networking>
    <printer>
      <cups_installation config:type="symbol">server</cups_installation>
      <default></default>
      <printcap config:type="list"/>
      <server_hostname></server_hostname>
      <spooler>cups</spooler>
    </printer>
    <runlevel>
      <default>3</default>
    </runlevel>
    <security>
      <console_shutdown>reboot</console_shutdown>
      <cracklib_dict_path>/usr/lib/cracklib_dict</cracklib_dict_path>
      <cwd_in_root_path>no</cwd_in_root_path>
      <cwd_in_user_path>no</cwd_in_user_path>
      <displaymanager_remote_access>no</displaymanager_remote_access>
      <enable_sysrq>no</enable_sysrq>
      <fail_delay>3</fail_delay>
      <faillog_enab>yes</faillog_enab>
      <gid_max>60000</gid_max>
      <gid_min>1000</gid_min>
      <kdm_shutdown>auto</kdm_shutdown>
      <lastlog_enab>yes</lastlog_enab>
      <obscure_checks_enab>yes</obscure_checks_enab>
      <pass_max_days>99999</pass_max_days>
      <pass_max_len>8</pass_max_len>
      <pass_min_days>0</pass_min_days>
      <pass_min_len>5</pass_min_len>
      <pass_warn_age>7</pass_warn_age>
      <passwd_encryption>des</passwd_encryption>
      <passwd_use_cracklib>yes</passwd_use_cracklib>
      <permission_security>easy</permission_security>
      <run_updatedb_as>nobody</run_updatedb_as>
      <system_gid_max>499</system_gid_max>
      <system_gid_min>100</system_gid_min>
      <system_uid_max>499</system_uid_max>
      <system_uid_min>100</system_uid_min>
      <uid_max>60000</uid_max>
      <uid_min>1000</uid_min>
      <useradd_cmd>/usr/sbin/useradd.local</useradd_cmd>
      <userdel_postcmd>/usr/sbin/userdel-post.local</userdel_postcmd>
      <userdel_precmd>/usr/sbin/userdel-pre.local</userdel_precmd>
    </security>
    <sound>
      <configure_detected config:type="boolean">false</configure_detected>
      <modules_conf config:type="list"/>
      <rc_vars/>
      <volume_settings config:type="list"/>
    </sound>
    <users config:type="list">
      <user>
        <encrypted config:type="boolean">false</encrypted>
        <user_password>%s</user_password>
        <username>root</username>
      </user>
    </users>
    <scripts>
      <chroot-scripts config:type="list"/>      
      <post-scripts config:type="list"/>
      <pre-scripts config:type="list"/>      
      <init-scripts config:type="list">
        <script>
          <filename>post.sh</filename>
          <interpreter>shell</interpreter> 
          <source><![CDATA[
#!/bin/sh

mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
]]>
          </source>
        </script>
      </init-scripts>
    </scripts>
  </configure>
  <install>
    <bootloader>
      <activate config:type="boolean">true</activate>
      <device_map config:type="list">
        <device_map_entry>
          <firmware>(hd0)</firmware>
          <linux>/dev/%s</linux>
        </device_map_entry>
      </device_map>
      <global config:type="list">
        <global_entry>
          <key>color</key>
          <value>white/blue black/light-gray</value>
        </global_entry>
        <global_entry>
          <key>default</key>
          <value config:type="integer">0</value>
        </global_entry>
        <global_entry>
          <key>timeout</key>
          <value config:type="integer">8</value>
        </global_entry>
      </global>
      <loader_device>/dev/sda</loader_device>
      <loader_type>grub</loader_type>
      <location>mbr</location>
      <repl_mbr config:type="boolean">true</repl_mbr>
      <sections config:type="list">
        <section config:type="list">
          <section_entry>
            <key>title</key>
            <value>Linux</value>
          </section_entry>
          <section_entry>
            <key>root</key>
            <value>(hd0,0)</value>
          </section_entry>
          <section_entry>
            <key>kernel</key>
            <value>/boot/vmlinuz root=/dev/%s2 selinux=0 serial console=ttyS0,115200 load_ramdisk=1 splash=silent showopts elevator=cfq</value>
          </section_entry>
          <section_entry>
            <key>initrd</key>
            <value>/boot/initrd</value>
          </section_entry>
        </section>
      </sections>
    </bootloader>
    <general>
      <clock>
        <hwclock>localtime</hwclock>
        <timezone>%s</timezone>
      </clock>
      <keyboard>
        <keymap>english-uk</keymap>
      </keyboard>
      <language>en_GB</language>
      <mode>
        <confirm config:type="boolean">false</confirm>
        <forceboot config:type="boolean">false</forceboot>
      </mode>
      <mouse>
        <id>none</id>
      </mouse>
      <signature-handling>
        <accept_verification_failed config:type="boolean">true</accept_verification_failed>
        <accept_file_without_checksum config:type="boolean">true</accept_file_without_checksum> 
      </signature-handling>  
    </general>
    <partitioning config:type="list">
      <drive>
        <device>/dev/%s</device>
        <initialize config:type="boolean">false</initialize>
        <partitions config:type="list">
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/boot</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>%sM</size>
          </partition>
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>10G</size>
          </partition>
        </partitions>
        <use>all</use>
      </drive>
    </partitioning>
    <software>
      <addons config:type="list">
        <addon>Base-System</addon>
        <addon>Basis-Sound</addon>
        <addon>Kde-Desktop</addon>
        <addon>Linux-Tools</addon>
        <addon>Print-Server</addon>
        <addon>SuSE-Documentation</addon>
        <addon>X11</addon>
        <addon>YaST2</addon>
        <addon>auth</addon>
        <addon>Basis-Devel</addon>
      </addons>
      <base>default</base>
      <remove-packages config:type="list">
        <package>sles-admin_en</package>
      </remove-packages>
      <packages config:type="list">
        <package>wget</package>
        <package>python</package>
      </packages>
    </software>
  </install>
</profile>
""" % (self.ethDevice,
       self._password(),
       self.signalDir,
       self.mainDisk,
       self.mainDisk,
       self._timezone(),
       self.mainDisk,
       self.bootDiskSize
       )
        return ks
 
    def _generateSLED11(self):
        ks="""<?xml version="1.0"?>
<!DOCTYPE profile SYSTEM "/usr/share/autoinstall/dtd/profile.dtd">
<profile xmlns="http://www.suse.com/1.0/yast2ns" xmlns:config="http://www.suse.com/1.0/configns">
  <configure>
    <networking>
      <dns>
        <dhcp_hostname config:type="boolean">false</dhcp_hostname>
        <dhcp_resolv config:type="boolean">false</dhcp_resolv>
      </dns>
      <routing>
        <ip_forward config:type="boolean">false</ip_forward>
      </routing>
      <interfaces config:type="list">
        <interface>
          <bootproto>dhcp</bootproto>
          <device>%s</device>        
          <startmode>onboot</startmode>
        </interface>
      </interfaces>
    </networking>
    <printer>
      <cups_installation config:type="symbol">server</cups_installation>
      <default></default>
      <printcap config:type="list"/>
      <server_hostname></server_hostname>
      <spooler>cups</spooler>
    </printer>
    <runlevel>
      <default>3</default>
    </runlevel>
    <security>
      <console_shutdown>reboot</console_shutdown>
      <cracklib_dict_path>/usr/lib/cracklib_dict</cracklib_dict_path>
      <cwd_in_root_path>no</cwd_in_root_path>
      <cwd_in_user_path>no</cwd_in_user_path>
      <displaymanager_remote_access>no</displaymanager_remote_access>
      <enable_sysrq>no</enable_sysrq>
      <fail_delay>3</fail_delay>
      <faillog_enab>yes</faillog_enab>
      <gid_max>60000</gid_max>
      <gid_min>1000</gid_min>
      <kdm_shutdown>auto</kdm_shutdown>
      <lastlog_enab>yes</lastlog_enab>
      <obscure_checks_enab>yes</obscure_checks_enab>
      <pass_max_days>99999</pass_max_days>
      <pass_max_len>8</pass_max_len>
      <pass_min_days>0</pass_min_days>
      <pass_min_len>5</pass_min_len>
      <pass_warn_age>7</pass_warn_age>
      <passwd_encryption>des</passwd_encryption>
      <passwd_use_cracklib>yes</passwd_use_cracklib>
      <permission_security>easy</permission_security>
      <run_updatedb_as>nobody</run_updatedb_as>
      <system_gid_max>499</system_gid_max>
      <system_gid_min>100</system_gid_min>
      <system_uid_max>499</system_uid_max>
      <system_uid_min>100</system_uid_min>
      <uid_max>60000</uid_max>
      <uid_min>1000</uid_min>
      <useradd_cmd>/usr/sbin/useradd.local</useradd_cmd>
      <userdel_postcmd>/usr/sbin/userdel-post.local</userdel_postcmd>
      <userdel_precmd>/usr/sbin/userdel-pre.local</userdel_precmd>
    </security>
    <sound>
      <configure_detected config:type="boolean">false</configure_detected>
      <modules_conf config:type="list"/>
      <rc_vars/>
      <volume_settings config:type="list"/>
    </sound>
    <users config:type="list">
      <user>
        <encrypted config:type="boolean">false</encrypted>
        <user_password>%s</user_password>
        <username>root</username>
      </user>
    </users>
    <scripts>
      <chroot-scripts config:type="list"/>      
      <post-scripts config:type="list"/>
      <pre-scripts config:type="list"/>      
      <init-scripts config:type="list">
        <script>
          <filename>post.sh</filename>
          <interpreter>shell</interpreter> 
          <source><![CDATA[
#!/bin/sh

mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s
sleep 120
%s
]]>
          </source>
        </script>
      </init-scripts>
    </scripts>
  </configure>
  <install>
    <bootloader>
      <activate config:type="boolean">true</activate>
      <device_map config:type="list">
        <device_map_entry>
          <firmware>(hd0)</firmware>
          <linux>/dev/%s</linux>
        </device_map_entry>
      </device_map>
      <global config:type="list">
        <global_entry>
          <key>color</key>
          <value>white/blue black/light-gray</value>
        </global_entry>
        <global_entry>
          <key>default</key>
          <value>0</value>
        </global_entry>
        <global_entry>
          <key>timeout</key>
          <value>5</value>
        </global_entry>
      </global>
      <loader_device>/dev/%s</loader_device>
      <loader_type>grub</loader_type>
      <location>mbr</location>
      <repl_mbr config:type="boolean">true</repl_mbr>
      <sections config:type="list">
        <section config:type="list">
          <section_entry>
            <key>title</key>
            <value>Linux</value>
          </section_entry>
          <section_entry>
            <key>root</key>
            <value>(hd0,0)</value>
          </section_entry>
          <section_entry>
            <key>kernel</key>
            <value>/boot/vmlinuz root=/dev/%s2 selinux=0 serial console=ttyS0,115200 load_ramdisk=1 splash=silent showopts elevator=cfq</value>
          </section_entry>
          <section_entry>
            <key>initrd</key>
            <value>/boot/initrd</value>
          </section_entry>
        </section>
      </sections>
    </bootloader>
    <general>
      <clock>
        <hwclock>localtime</hwclock>
        <timezone>%s</timezone>
      </clock>
      <keyboard>
        <keymap>english-uk</keymap>
      </keyboard>
      <language>en_GB</language>
      <mode>
        <confirm config:type="boolean">false</confirm>
        <forceboot config:type="boolean">false</forceboot>
      </mode>
      <mouse>
        <id>none</id>
      </mouse>
      <signature-handling>
        <accept_verification_failed config:type="boolean">true</accept_verification_failed>
        <accept_file_without_checksum config:type="boolean">true</accept_file_without_checksum> 
      </signature-handling>  
    </general>
    <partitioning config:type="list">
      <drive>
        <device>/dev/%s</device>
        <initialize config:type="boolean">false</initialize>
        <partitions config:type="list">
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/boot</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>%sM</size>
          </partition>
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>7G</size>
          </partition>
        </partitions>
        <use>all</use>
      </drive>
    </partitioning>
    <software>
      <patterns config:type="list">
        <pattern>Basis-Devel</pattern>
      </patterns>
    </software>
  </install>
</profile>
""" % (self.ethDevice,
       self._password(),
       self.signalDir,
       self._postInstall(),
       self._rebootAfterInstall(),
       self.mainDisk,
       self.mainDisk,
       self.mainDisk,
       self._timezone(),
       self.mainDisk,
       self._bootDiskSize()
       )
        return ks

    def _generateSLES12(self):
        ks = """<?xml version="1.0"?>
<!DOCTYPE profile>
<profile xmlns="http://www.suse.com/1.0/yast2ns" xmlns:config="http://www.suse.com/1.0/configns">
  <add-on>
    <add_on_products config:type="list"/>
  </add-on>
  <bootloader>
    <device_map config:type="list">
      <device_map_entry>
        <firmware>hd0</firmware>
        <linux>/dev/%s</linux>
      </device_map_entry>
    </device_map>
    <global>
      <activate>true</activate>
      <append>   resume=/dev/%s2 splash=silent quiet showopts</append>
      <append_failsafe>showopts apm=off noresume edd=off powersaved=off nohz=off highres=off processor.max_cstate=1 nomodeset x11failsafe</append_failsafe>
      <boot_boot>false</boot_boot>
      <boot_custom/>
      <boot_extended>false</boot_extended>
      <boot_mbr>true</boot_mbr>
      <boot_root>true</boot_root>
      <default>0</default>
      <distributor>SUSE Linux Enterprise Server 12 (RC1)</distributor>
      <generic_mbr>true</generic_mbr>
      <gfxmode>auto</gfxmode>
      <hiddenmenu>false</hiddenmenu>
      <os_prober>false</os_prober>
      <terminal>gfxterm</terminal>
      <timeout config:type="integer">8</timeout>
      <vgamode/>
    </global>
    <loader_type>grub2</loader_type>
    <sections config:type="list"/>
  </bootloader>
  <deploy_image>
    <image_installation config:type="boolean">false</image_installation>
  </deploy_image>
  <general>
    <ask-list config:type="list"/>
    <mode>
      <confirm config:type="boolean">false</confirm>
    </mode>
    <proposals config:type="list"/>
    <signature-handling>
      <accept_file_without_checksum config:type="boolean">true</accept_file_without_checksum>
      <accept_non_trusted_gpg_key config:type="boolean">true</accept_non_trusted_gpg_key>
      <accept_unknown_gpg_key config:type="boolean">true</accept_unknown_gpg_key>
      <accept_unsigned_file config:type="boolean">true</accept_unsigned_file>
      <accept_verification_failed config:type="boolean">false</accept_verification_failed>
      <import_gpg_key config:type="boolean">true</import_gpg_key>
    </signature-handling>
    <storage>
      <partition_alignment config:type="symbol">align_optimal</partition_alignment>
      <start_multipath config:type="boolean">false</start_multipath>
    </storage>
  </general>
  <groups config:type="list">
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>100</gid>
      <group_password>x</group_password>
      <groupname>users</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>41</gid>
      <group_password>x</group_password>
      <groupname>xok</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>5</gid>
      <group_password>x</group_password>
      <groupname>tty</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>12</gid>
      <group_password>x</group_password>
      <groupname>mail</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>496</gid>
      <group_password>x</group_password>
      <groupname>polkitd</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>7</gid>
      <group_password>x</group_password>
      <groupname>lp</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>62</gid>
      <group_password>x</group_password>
      <groupname>man</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>10</gid>
      <group_password>x</group_password>
      <groupname>wheel</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>8</gid>
      <group_password>x</group_password>
      <groupname>www</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>0</gid>
      <group_password>x</group_password>
      <groupname>root</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>65534</gid>
      <group_password>x</group_password>
      <groupname>nogroup</groupname>
      <userlist>nobody</userlist>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>20</gid>
      <group_password>x</group_password>
      <groupname>cdrom</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>498</gid>
      <group_password>x</group_password>
      <groupname>sshd</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>40</gid>
      <group_password>x</group_password>
      <groupname>games</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>16</gid>
      <group_password>x</group_password>
      <groupname>dialout</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>32</gid>
      <group_password>x</group_password>
      <groupname>public</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>6</gid>
      <group_password>x</group_password>
      <groupname>disk</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>497</gid>
      <group_password>x</group_password>
      <groupname>tape</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>54</gid>
      <group_password>x</group_password>
      <groupname>lock</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>13</gid>
      <group_password>x</group_password>
      <groupname>news</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>495</gid>
      <group_password>x</group_password>
      <groupname>nscd</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>3</gid>
      <group_password>x</group_password>
      <groupname>sys</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>43</gid>
      <group_password>x</group_password>
      <groupname>modem</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>499</gid>
      <group_password>x</group_password>
      <groupname>messagebus</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>21</gid>
      <group_password>x</group_password>
      <groupname>console</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>22</gid>
      <group_password>x</group_password>
      <groupname>utmp</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>14</gid>
      <group_password>x</group_password>
      <groupname>uucp</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>33</gid>
      <group_password>x</group_password>
      <groupname>video</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>17</gid>
      <group_password>x</group_password>
      <groupname>audio</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>42</gid>
      <group_password>x</group_password>
      <groupname>trusted</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>65533</gid>
      <group_password>x</group_password>
      <groupname>nobody</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>15</gid>
      <group_password>x</group_password>
      <groupname>shadow</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>49</gid>
      <group_password>x</group_password>
      <groupname>ftp</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>9</gid>
      <group_password>x</group_password>
      <groupname>kmem</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>1</gid>
      <group_password>x</group_password>
      <groupname>bin</groupname>
      <userlist>daemon</userlist>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>19</gid>
      <group_password>x</group_password>
      <groupname>floppy</groupname>
      <userlist/>
    </group>
    <group>
      <encrypted config:type="boolean">true</encrypted>
      <gid>2</gid>
      <group_password>x</group_password>
      <groupname>daemon</groupname>
      <userlist/>
    </group>
  </groups>
  <kdump>
    <add_crash_kernel config:type="boolean">false</add_crash_kernel>
    <crash_kernel>176M-:88M</crash_kernel>
    <general>
      <KDUMP_COMMANDLINE/>
      <KDUMP_COMMANDLINE_APPEND/>
      <KDUMP_COPY_KERNEL>yes</KDUMP_COPY_KERNEL>
      <KDUMP_DUMPFORMAT>lzo</KDUMP_DUMPFORMAT>
      <KDUMP_DUMPLEVEL>31</KDUMP_DUMPLEVEL>
      <KDUMP_FREE_DISK_SIZE>64</KDUMP_FREE_DISK_SIZE>
      <KDUMP_IMMEDIATE_REBOOT>yes</KDUMP_IMMEDIATE_REBOOT>
      <KDUMP_KEEP_OLD_DUMPS>5</KDUMP_KEEP_OLD_DUMPS>
      <KDUMP_KERNELVER/>
      <KDUMP_NOTIFICATION_CC/>
      <KDUMP_NOTIFICATION_TO/>
      <KDUMP_SAVEDIR>file:///var/crash</KDUMP_SAVEDIR>
      <KDUMP_SMTP_PASSWORD/>
      <KDUMP_SMTP_SERVER/>
      <KDUMP_SMTP_USER/>
      <KDUMP_TRANSFER/>
      <KDUMP_VERBOSE>3</KDUMP_VERBOSE>
      <KEXEC_OPTIONS/>
    </general>
  </kdump>
  <keyboard>
    <keyboard_values>
      <delay/>
      <discaps config:type="boolean">false</discaps>
      <numlock>bios</numlock>
      <rate/>
    </keyboard_values>
    <keymap>english-us</keymap>
  </keyboard>
  <language>
    <language>en_US</language>
    <languages/>
  </language>
  <login_settings/>
  <networking>
    <dns>
      <dhcp_hostname config:type="boolean">false</dhcp_hostname>
      <resolv_conf_policy/>
      <write_hostname config:type="boolean">false</write_hostname>
    </dns>
    <interfaces config:type="list">
      <interface>
        <bootproto>dhcp</bootproto>
        <device>%s</device>
        <dhclient_set_default_route>yes</dhclient_set_default_route>
        <startmode>auto</startmode>
      </interface>
      <interface>
        <bootproto>static</bootproto>
        <broadcast>127.255.255.255</broadcast>
        <device>lo</device>
        <firewall>no</firewall>
        <ipaddr>127.0.0.1</ipaddr>
        <netmask>255.0.0.0</netmask>
        <network>127.0.0.0</network>
        <prefixlen>8</prefixlen>
        <startmode>nfsroot</startmode>
        <usercontrol>no</usercontrol>
      </interface>
    </interfaces>
    <ipv6 config:type="boolean">true</ipv6>
    <keep_install_network config:type="boolean">false</keep_install_network>
    <managed config:type="boolean">false</managed>
    <routing>
      <ipv4_forward config:type="boolean">false</ipv4_forward>
      <ipv6_forward config:type="boolean">false</ipv6_forward>
    </routing>
  </networking>
  <ntp-client>
    <ntp_policy>auto</ntp_policy>
    <peers config:type="list"/>
    <start_at_boot config:type="boolean">true</start_at_boot>
    <start_in_chroot config:type="boolean">false</start_in_chroot>
    <sync_interval config:type="integer">5</sync_interval>
    <synchronize_time config:type="boolean">false</synchronize_time>
  </ntp-client>
  <partitioning config:type="list">
    <drive>
      <device>/dev/%s</device>
      <disklabel>msdos</disklabel>
      <enable_snapshots config:type="boolean">true</enable_snapshots>
      <initialize config:type="boolean">true</initialize>
      <partitions config:type="list">
        <partition>
          <create config:type="boolean">true</create>
          <crypt_fs config:type="boolean">false</crypt_fs>
          <filesystem config:type="symbol">ext3</filesystem>
          <format config:type="boolean">true</format>
          <fstopt>acl,user_xattr</fstopt>
          <loop_fs config:type="boolean">false</loop_fs>
          <mount>/</mount>
          <mountby config:type="symbol">uuid</mountby>
          <partition_id config:type="integer">131</partition_id>
          <partition_nr config:type="integer">1</partition_nr>
          <resize config:type="boolean">false</resize>
          <size>7542581760</size>
        </partition>
        <partition>
          <create config:type="boolean">true</create>
          <crypt_fs config:type="boolean">false</crypt_fs>
          <filesystem config:type="symbol">swap</filesystem>
          <format config:type="boolean">true</format>
          <loop_fs config:type="boolean">false</loop_fs>
          <mount>swap</mount>
          <mountby config:type="symbol">uuid</mountby>
          <partition_id config:type="integer">130</partition_id>
          <partition_nr config:type="integer">2</partition_nr>
          <resize config:type="boolean">false</resize>
          <size>1028160000</size>
        </partition>
      </partitions>
      <pesize/>
      <type config:type="symbol">CT_DISK</type>
      <use>all</use>
    </drive>
  </partitioning>
  <proxy>
    <enabled config:type="boolean">false</enabled>
    <ftp_proxy/>
    <http_proxy/>
    <https_proxy/>
    <no_proxy>localhost, 127.0.0.1</no_proxy>
    <proxy_password/>
    <proxy_user/>
  </proxy>
  <report>
    <errors>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </errors>
    <messages>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </messages>
    <warnings>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </warnings>
    <yesno_messages>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </yesno_messages>
  </report>
  <runlevel>
    <default_target>multi-user</default_target>
    <services config:type="list"/>
  </runlevel>
  <services-manager>
    <default_target>multi-user</default_target>
    <services>
      <disable config:type="list"/>
      <enable config:type="list">
        <service>sshd</service>
      </enable>
    </services>
  </services-manager>
  <software>
    <image/>
    <instsource/>
    <patterns config:type="list">
      <pattern>32bit</pattern>
      <pattern>Basis-Devel</pattern>
      <pattern>Minimal</pattern>
      %s
    </patterns>
  </software>
  <suse_register>
    <do_registration config:type="boolean">false</do_registration>
  </suse_register>
  <timezone>
    <hwclock>UTC</hwclock>
    <timezone>Etc/UTC</timezone>
  </timezone>
  <user_defaults>
    <expire/>
    <group>100</group>
    <groups/>
    <home>/home</home>
    <inactive>-1</inactive>
    <no_groups config:type="boolean">true</no_groups>
    <shell>/bin/bash</shell>
    <skel>/etc/skel</skel>
    <umask>022</umask>
  </user_defaults>
  <users config:type="list">
    <user>
      <encrypted config:type="boolean">false</encrypted>
      <fullname>xenrtd</fullname>
      <gid>100</gid>
      <home>/home/xenrtd</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact>-1</inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>1000</uid>
      <user_password>%s</user_password>
      <username>xenrtd</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Manual pages viewer</fullname>
      <gid>62</gid>
      <home>/var/cache/man</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>13</uid>
      <user_password>*</user_password>
      <username>man</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Unix-to-Unix CoPy system</fullname>
      <gid>14</gid>
      <home>/etc/uucp</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>10</uid>
      <user_password>*</user_password>
      <username>uucp</username>
    </user>
    <user>
      <encrypted config:type="boolean">false</encrypted>
      <fullname>root</fullname>
      <gid>0</gid>
      <home>/root</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>0</uid>
      <user_password>%s</user_password>
      <username>root</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>nobody</fullname>
      <gid>65533</gid>
      <home>/var/lib/nobody</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>65534</uid>
      <user_password>*</user_password>
      <username>nobody</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Mailer daemon</fullname>
      <gid>12</gid>
      <home>/var/spool/clientmqueue</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>8</uid>
      <user_password>*</user_password>
      <username>mail</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>User for polkitd</fullname>
      <gid>496</gid>
      <home>/var/lib/polkit</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/sbin/nologin</shell>
      <uid>497</uid>
      <user_password>!</user_password>
      <username>polkitd</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Printing daemon</fullname>
      <gid>7</gid>
      <home>/var/spool/lpd</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>4</uid>
      <user_password>*</user_password>
      <username>lp</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>User for D-Bus</fullname>
      <gid>499</gid>
      <home>/var/run/dbus</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>499</uid>
      <user_password>!</user_password>
      <username>messagebus</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Daemon</fullname>
      <gid>2</gid>
      <home>/sbin</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>2</uid>
      <user_password>*</user_password>
      <username>daemon</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>News system</fullname>
      <gid>13</gid>
      <home>/etc/news</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>9</uid>
      <user_password>*</user_password>
      <username>news</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>User for nscd</fullname>
      <gid>495</gid>
      <home>/run/nscd</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/sbin/nologin</shell>
      <uid>496</uid>
      <user_password>!</user_password>
      <username>nscd</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Games account</fullname>
      <gid>100</gid>
      <home>/var/games</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>12</uid>
      <user_password>*</user_password>
      <username>games</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>user for rpcbind</fullname>
      <gid>65534</gid>
      <home>/var/lib/empty</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/sbin/nologin</shell>
      <uid>495</uid>
      <user_password>!</user_password>
      <username>rpc</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>SSH daemon</fullname>
      <gid>498</gid>
      <home>/var/lib/sshd</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>498</uid>
      <user_password>!</user_password>
      <username>sshd</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>WWW daemon apache</fullname>
      <gid>8</gid>
      <home>/var/lib/wwwrun</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>30</uid>
      <user_password>*</user_password>
      <username>wwwrun</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>bin</fullname>
      <gid>1</gid>
      <home>/bin</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>1</uid>
      <user_password>*</user_password>
      <username>bin</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>FTP account</fullname>
      <gid>49</gid>
      <home>/srv/ftp</home>
      <password_settings>
        <expire/>
        <flag/>
        <inact/>
        <max/>
        <min/>
        <warn/>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>40</uid>
      <user_password>*</user_password>
      <username>ftp</username>
    </user>
  </users>
  <scripts>
    <chroot-scripts config:type="list"/>
    <post-scripts config:type="list"/>
    <pre-scripts config:type="list"/>
    <init-scripts config:type="list">
      <script>
        <filename>post.sh</filename>
        <interpreter>shell</interpreter>
        <source><![CDATA[
#!/bin/sh

echo ulimit -c unlimited >> /etc/profile.local
systemctl enable sshd
systemctl start sshd
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
]]>
        </source>
      </script>
    </init-scripts>
  </scripts>
</profile>""" % (self.mainDisk,
                 self.mainDisk,
                 self.ethDevice,
                 self.mainDisk,
                 self._package(),
                 self._password(),
                 self._password(),
                 self.signalDir)
        return ks

    def _generateSLES11x(self):
        SLES111=["<package>stunnel</package>",
                "echo ulimit -v unlimited >> /etc/profile.local",
                "(sleep 120; %s) > /dev/null 2>&1 &"%(self._rebootAfterInstall()),
                ""]
        SLES11=["",
                "",
               "sleep 120",
               "%s"%(self._rebootAfterInstall())]
        diffSLES=[]
        if re.match(r'sles11[123]', self.distro):
            diffSLES=SLES111
        else:
            diffSLES=SLES11
        
        ks="""<?xml version="1.0"?>
<!DOCTYPE profile>
<profile xmlns="http://www.suse.com/1.0/yast2ns" xmlns:config="http://www.suse.com/1.0/configns">
  <add-on>
    <add_on_products config:type="list"/>
  </add-on>
  <bootloader>
    <device_map config:type="list">
      <device_map_entry>
        <firmware>hd0</firmware>
        <linux>/dev/%s</linux>
      </device_map_entry>
    </device_map>
    <global>
      <activate>true</activate>
      <boot_root>true</boot_root>
      <default>Xen -- SUSE Linux Enterprise Server 11 - 2.6.27.19-5</default>
      <generic_mbr>true</generic_mbr>
      <gfxmenu>/boot/message</gfxmenu>
      <lines_cache_id>1</lines_cache_id>
      <timeout config:type="integer">8</timeout>
    </global>
    <initrd_modules config:type="list">
      <initrd_module>
        <module>xenblk</module>
      </initrd_module>
      <initrd_module>
        <module>processor</module>
      </initrd_module>
      <initrd_module>
        <module>thermal</module>
      </initrd_module>
      <initrd_module>
        <module>fan</module>
      </initrd_module>
      <initrd_module>
        <module>jbd</module>
      </initrd_module>
      <initrd_module>
        <module>ext3</module>
      </initrd_module>
    </initrd_modules>
    <loader_type>grub</loader_type>
    <sections config:type="list">
      <section>
        <append>console=ttyS0 xencons=ttyS resume=/dev/%s1 splash=silent showopts</append>
        <image>/boot/vmlinuz-2.6.27.19-5-xen</image>
        <initial>1</initial>
        <initrd>/boot/initrd-2.6.27.19-5-xen</initrd>
        <lines_cache_id>0</lines_cache_id>
        <name>Xen -- SUSE Linux Enterprise Server 11 - 2.6.27.19-5</name>
        <original_name>linux</original_name>
        <root>/dev/%s2</root>
        <type>image</type>
      </section>
    </sections>
  </bootloader>
  <ca_mgm>
    <CAName>YaST_Default_CA</CAName>
    <ca_commonName>YaST Default CA (linux-r5kd)</ca_commonName>
    <country>US</country>
    <locality></locality>
    <organisation></organisation>
    <organisationUnit></organisationUnit>
    <password>ENTER PASSWORD HERE</password>
    <server_commonName>linux-r5kd.site</server_commonName>
    <server_email>postmaster@site</server_email>
    <state></state>
    <takeLocalServerName config:type="boolean">false</takeLocalServerName>
  </ca_mgm>
  <deploy_image>
    <image_installation config:type="boolean">false</image_installation>
  </deploy_image>
  <firewall>
    <FW_ALLOW_FW_BROADCAST_DMZ>no</FW_ALLOW_FW_BROADCAST_DMZ>
    <FW_ALLOW_FW_BROADCAST_EXT>no</FW_ALLOW_FW_BROADCAST_EXT>
    <FW_ALLOW_FW_BROADCAST_INT>no</FW_ALLOW_FW_BROADCAST_INT>
    <FW_CONFIGURATIONS_DMZ></FW_CONFIGURATIONS_DMZ>
    <FW_CONFIGURATIONS_EXT></FW_CONFIGURATIONS_EXT>
    <FW_CONFIGURATIONS_INT></FW_CONFIGURATIONS_INT>
    <FW_DEV_DMZ></FW_DEV_DMZ>
    <FW_DEV_EXT>any eth0</FW_DEV_EXT>
    <FW_DEV_INT></FW_DEV_INT>
    <FW_FORWARD_ALWAYS_INOUT_DEV></FW_FORWARD_ALWAYS_INOUT_DEV>
    <FW_FORWARD_MASQ></FW_FORWARD_MASQ>
    <FW_IGNORE_FW_BROADCAST_DMZ>no</FW_IGNORE_FW_BROADCAST_DMZ>
    <FW_IGNORE_FW_BROADCAST_EXT>yes</FW_IGNORE_FW_BROADCAST_EXT>
    <FW_IGNORE_FW_BROADCAST_INT>no</FW_IGNORE_FW_BROADCAST_INT>
    <FW_IPSEC_TRUST>no</FW_IPSEC_TRUST>
    <FW_LOAD_MODULES>nf_conntrack_netbios_ns</FW_LOAD_MODULES>
    <FW_LOG_ACCEPT_ALL>no</FW_LOG_ACCEPT_ALL>
    <FW_LOG_ACCEPT_CRIT>yes</FW_LOG_ACCEPT_CRIT>
    <FW_LOG_DROP_ALL>no</FW_LOG_DROP_ALL>
    <FW_LOG_DROP_CRIT>yes</FW_LOG_DROP_CRIT>
    <FW_MASQUERADE>no</FW_MASQUERADE>
    <FW_PROTECT_FROM_INT>no</FW_PROTECT_FROM_INT>
    <FW_ROUTE>no</FW_ROUTE>
    <FW_SERVICES_ACCEPT_DMZ></FW_SERVICES_ACCEPT_DMZ>
    <FW_SERVICES_ACCEPT_EXT></FW_SERVICES_ACCEPT_EXT>
    <FW_SERVICES_ACCEPT_INT></FW_SERVICES_ACCEPT_INT>
    <FW_SERVICES_ACCEPT_RELATED_DMZ></FW_SERVICES_ACCEPT_RELATED_DMZ>
    <FW_SERVICES_ACCEPT_RELATED_EXT></FW_SERVICES_ACCEPT_RELATED_EXT>
    <FW_SERVICES_ACCEPT_RELATED_INT></FW_SERVICES_ACCEPT_RELATED_INT>
    <FW_SERVICES_DMZ_IP></FW_SERVICES_DMZ_IP>
    <FW_SERVICES_DMZ_RPC></FW_SERVICES_DMZ_RPC>
    <FW_SERVICES_DMZ_TCP></FW_SERVICES_DMZ_TCP>
    <FW_SERVICES_DMZ_UDP></FW_SERVICES_DMZ_UDP>
    <FW_SERVICES_EXT_IP></FW_SERVICES_EXT_IP>
    <FW_SERVICES_EXT_RPC></FW_SERVICES_EXT_RPC>
    <FW_SERVICES_EXT_TCP></FW_SERVICES_EXT_TCP>
    <FW_SERVICES_EXT_UDP></FW_SERVICES_EXT_UDP>
    <FW_SERVICES_INT_IP></FW_SERVICES_INT_IP>
    <FW_SERVICES_INT_RPC></FW_SERVICES_INT_RPC>
    <FW_SERVICES_INT_TCP></FW_SERVICES_INT_TCP>
    <FW_SERVICES_INT_UDP></FW_SERVICES_INT_UDP>
    <enable_firewall config:type="boolean">false</enable_firewall>
    <start_firewall config:type="boolean">false</start_firewall>
  </firewall>
  <general>
    <ask-list config:type="list"/>
    <mode>
      <confirm config:type="boolean">false</confirm>
    </mode>
    <mouse>
      <id>none</id>
    </mouse>
    <proposals config:type="list"/>
    <signature-handling>
      <accept_file_without_checksum config:type="boolean">true</accept_file_without_checksum>
      <accept_non_trusted_gpg_key config:type="boolean">true</accept_non_trusted_gpg_key>
      <accept_unknown_gpg_key config:type="boolean">true</accept_unknown_gpg_key>
      <accept_unsigned_file config:type="boolean">true</accept_unsigned_file>
      <accept_verification_failed config:type="boolean">false</accept_verification_failed>
      <import_gpg_key config:type="boolean">true</import_gpg_key>
    </signature-handling>
  </general>
  <groups config:type="list">
    <group>
      <group_password>x</group_password>
      <groupname>users</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>floppy</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>bin</groupname>
      <userlist>daemon</userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>xok</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>nobody</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>modem</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>lp</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>tty</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>postfix</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>uuidd</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>gdm</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>nogroup</groupname>
      <userlist>nobody</userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>maildrop</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>messagebus</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>video</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>sys</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>shadow</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>console</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>cdrom</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>haldaemon</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>trusted</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>dialout</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>polkituser</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>pulse</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>wheel</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>www</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>games</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>disk</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>audio</groupname>
      <userlist>pulse</userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>suse-ncc</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>ftp</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>at</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>kmem</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>public</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>root</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>mail</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>daemon</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>ntp</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>sfcb</groupname>
      <userlist>root</userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>uucp</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>pulse-access</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>ntadmin</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>pulse-rt</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>man</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>utmp</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>x</group_password>
      <groupname>news</groupname>
      <userlist></userlist>
    </group>
    <group>
      <group_password>!</group_password>
      <groupname>sshd</groupname>
      <userlist></userlist>
    </group>
  </groups>
  <host>
    <hosts config:type="list">
      <hosts_entry>
        <host_address>127.0.0.1</host_address>
        <names config:type="list">
          <name>localhost</name>
        </names>
      </hosts_entry>
      <hosts_entry>
        <host_address>::1</host_address>
        <names config:type="list">
          <name>localhost ipv6-localhost ipv6-loopback</name>
        </names>
      </hosts_entry>
      <hosts_entry>
        <host_address>fe00::0</host_address>
        <names config:type="list">
          <name>ipv6-localnet</name>
        </names>
      </hosts_entry>
      <hosts_entry>
        <host_address>ff00::0</host_address>
        <names config:type="list">
          <name>ipv6-mcastprefix</name>
        </names>
      </hosts_entry>
      <hosts_entry>
        <host_address>ff02::1</host_address>
        <names config:type="list">
          <name>ipv6-allnodes</name>
        </names>
      </hosts_entry>
      <hosts_entry>
        <host_address>ff02::2</host_address>
        <names config:type="list">
          <name>ipv6-allrouters</name>
        </names>
      </hosts_entry>
      <hosts_entry>
        <host_address>ff02::3</host_address>
        <names config:type="list">
          <name>ipv6-allhosts</name>
        </names>
      </hosts_entry>
    </hosts>
  </host>
  <iscsi-client>
    <initiatorname></initiatorname>
    <targets config:type="list"/>
    <version>1.0</version>
  </iscsi-client>
  <kdump>
    <add_crash_kernel config:type="boolean">false</add_crash_kernel>
    <crash_kernel>128M-:64M@16M</crash_kernel>
    <general>
      <KDUMPTOOL_FLAGS></KDUMPTOOL_FLAGS>
      <KDUMP_COMMANDLINE></KDUMP_COMMANDLINE>
      <KDUMP_COMMANDLINE_APPEND></KDUMP_COMMANDLINE_APPEND>
      <KDUMP_CONTINUE_ON_ERROR>false</KDUMP_CONTINUE_ON_ERROR>
      <KDUMP_COPY_KERNEL>yes</KDUMP_COPY_KERNEL>
      <KDUMP_DUMPFORMAT>compressed</KDUMP_DUMPFORMAT>
      <KDUMP_DUMPLEVEL>0</KDUMP_DUMPLEVEL>
      <KDUMP_FREE_DISK_SIZE>64</KDUMP_FREE_DISK_SIZE>
      <KDUMP_IMMEDIATE_REBOOT>yes</KDUMP_IMMEDIATE_REBOOT>
      <KDUMP_KEEP_OLD_DUMPS>5</KDUMP_KEEP_OLD_DUMPS>
      <KDUMP_KERNELVER></KDUMP_KERNELVER>
      <KDUMP_NETCONFIG>auto</KDUMP_NETCONFIG>
      <KDUMP_NOTIFICATION_CC></KDUMP_NOTIFICATION_CC>
      <KDUMP_NOTIFICATION_TO></KDUMP_NOTIFICATION_TO>
      <KDUMP_POSTSCRIPT></KDUMP_POSTSCRIPT>
      <KDUMP_PRESCRIPT></KDUMP_PRESCRIPT>
      <KDUMP_REQUIRED_PROGRAMS></KDUMP_REQUIRED_PROGRAMS>
      <KDUMP_SAVEDIR>file:///var/crash</KDUMP_SAVEDIR>
      <KDUMP_SMTP_PASSWORD></KDUMP_SMTP_PASSWORD>
      <KDUMP_SMTP_SERVER></KDUMP_SMTP_SERVER>
      <KDUMP_SMTP_USER></KDUMP_SMTP_USER>
      <KDUMP_TRANSFER></KDUMP_TRANSFER>
      <KDUMP_VERBOSE>3</KDUMP_VERBOSE>
      <KEXEC_OPTIONS></KEXEC_OPTIONS>
    </general>
  </kdump>
  <keyboard>
    <keymap>english-us</keymap>
  </keyboard>
  <language>
    <language>en_US</language>
    <languages></languages>
  </language>
  <ldap>
    <base_config_dn></base_config_dn>
    <bind_dn></bind_dn>
    <create_ldap config:type="boolean">false</create_ldap>
    <file_server config:type="boolean">false</file_server>
    <ldap_domain>dc=example,dc=com</ldap_domain>
    <ldap_server>127.0.0.1</ldap_server>
    <ldap_tls config:type="boolean">true</ldap_tls>
    <ldap_v2 config:type="boolean">false</ldap_v2>
    <login_enabled config:type="boolean">true</login_enabled>
    <member_attribute>member</member_attribute>
    <pam_password>exop</pam_password>
    <start_autofs config:type="boolean">false</start_autofs>
    <start_ldap config:type="boolean">false</start_ldap>
  </ldap>
  <login_settings/>
  <networking>
    <dhcp_options>
      <dhclient_client_id></dhclient_client_id>
      <dhclient_hostname_option>AUTO</dhclient_hostname_option>
    </dhcp_options>
    <dns>
      <dhcp_hostname config:type="boolean">true</dhcp_hostname>
      <domain>site</domain>
      <hostname>linux-r5kd</hostname>
      <resolv_conf_policy>auto</resolv_conf_policy>
    </dns>
    <interfaces config:type="list">
      <interface>
        <bootproto>dhcp4</bootproto>
        <device>%s</device>
        <name>Virtual Ethernet Card 0</name>
        <startmode>auto</startmode>
      </interface>
    </interfaces>
    <managed config:type="boolean">false</managed>
    <routing>
      <ip_forward config:type="boolean">false</ip_forward>
    </routing>
  </networking>
  <nis>
    <netconfig_policy>auto</netconfig_policy>
    <nis_broadcast config:type="boolean">false</nis_broadcast>
    <nis_broken_server config:type="boolean">false</nis_broken_server>
    <nis_domain></nis_domain>
    <nis_local_only config:type="boolean">false</nis_local_only>
    <nis_options></nis_options>
    <nis_other_domains config:type="list"/>
    <nis_servers config:type="list"/>
    <slp_domain/>
    <start_autofs config:type="boolean">false</start_autofs>
    <start_nis config:type="boolean">false</start_nis>
  </nis>
  <partitioning config:type="list">
    <drive>
      <device>/dev/%s</device>
      <initialize config:type="boolean">true</initialize>
      <partitions config:type="list">
        <partition>
          <create config:type="boolean">true</create>
          <crypt_fs config:type="boolean">false</crypt_fs>
          <filesystem config:type="symbol">swap</filesystem>
          <format config:type="boolean">true</format>
          <loop_fs config:type="boolean">false</loop_fs>
          <mount>swap</mount>
          <mountby config:type="symbol">device</mountby>
          <partition_id config:type="integer">130</partition_id>
          <partition_nr config:type="integer">1</partition_nr>
          <resize config:type="boolean">false</resize>
          <size>880072192</size>
        </partition>
        <partition>
          <create config:type="boolean">true</create>
          <crypt_fs config:type="boolean">false</crypt_fs>
          <filesystem config:type="symbol">ext3</filesystem>
          <format config:type="boolean">true</format>
          <loop_fs config:type="boolean">false</loop_fs>
          <mount>/</mount>
          <mountby config:type="symbol">device</mountby>
          <partition_id config:type="integer">131</partition_id>
          <partition_nr config:type="integer">2</partition_nr>
          <resize config:type="boolean">false</resize>
          <size>16280190976</size>
        </partition>
      </partitions>
      <pesize></pesize>
      <type config:type="symbol">CT_DISK</type>
      <use>all</use>
    </drive>
  </partitioning>
  <proxy>
    <enabled config:type="boolean">false</enabled>
    <ftp_proxy></ftp_proxy>
    <http_proxy></http_proxy>
    <https_proxy></https_proxy>
    <no_proxy>localhost, 127.0.0.1</no_proxy>
    <proxy_password></proxy_password>
    <proxy_user></proxy_user>
  </proxy>
  <report>
    <errors>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </errors>
    <messages>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </messages>
    <warnings>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </warnings>
    <yesno_messages>
      <log config:type="boolean">true</log>
      <show config:type="boolean">true</show>
      <timeout config:type="integer">0</timeout>
    </yesno_messages>
  </report>
  <runlevel>
    <default>3</default>
  </runlevel>
  <software>
    <packages config:type="list">
      <package>xen-libs</package>
      <package>xen-tools-domU</package>
      <package>yast2-trans-en_US</package>
      %s
    </packages>
    <patterns config:type="list">
      <pattern>Minimal</pattern>
      <pattern>WBEM</pattern>
      <pattern>apparmor</pattern>
      <pattern>base</pattern>
      <pattern>documentation</pattern>
      <pattern>gnome</pattern>
      <pattern>print_server</pattern>
      <pattern>x11</pattern>
      <pattern>Basis-Devel</pattern>
    </patterns>
    <remove-packages config:type="list">
      <package>gnome-session-branding-upstream</package>
      <package>libqt4-sql-sqlite</package>
      <package>lprng</package>
      <package>pcmciautils</package>
      <package>portmap</package>
      <package>rsyslog</package>
      <package>sendmail</package>
      <package>susehelp_de</package>
      <package>xpdf-tools</package>
      <package>yast2-control-center-qt</package>
    </remove-packages>
  </software>
  <timezone>
    <hwclock>UTC</hwclock>
    <timezone>%s</timezone>
  </timezone>
  <user_defaults>
    <expire></expire>
    <group>100</group>
    <groups>video,dialout</groups>
    <home>/home</home>
    <inactive>-1</inactive>
    <shell>/bin/bash</shell>
    <skel>/etc/skel</skel>
  </user_defaults>
  <users config:type="list">
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Games account</fullname>
      <gid>100</gid>
      <home>/var/games</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>12</uid>
      <user_password>*</user_password>
      <username>games</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>bin</fullname>
      <gid>1</gid>
      <home>/bin</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>1</uid>
      <user_password>*</user_password>
      <username>bin</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>nobody</fullname>
      <gid>65533</gid>
      <home>/var/lib/nobody</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>65534</uid>
      <user_password>*</user_password>
      <username>nobody</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Printing daemon</fullname>
      <gid>7</gid>
      <home>/var/spool/lpd</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>4</uid>
      <user_password>*</user_password>
      <username>lp</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Postfix Daemon</fullname>
      <gid>51</gid>
      <home>/var/spool/postfix</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>51</uid>
      <user_password>*</user_password>
      <username>postfix</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>User for uuidd</fullname>
      <gid>103</gid>
      <home>/var/run/uuidd</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>102</uid>
      <user_password>*</user_password>
      <username>uuidd</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Novell Customer Center User</fullname>
      <gid>110</gid>
      <home>/var/lib/YaST2/suse-ncc-fakehome</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>105</uid>
      <user_password>*</user_password>
      <username>suse-ncc</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>FTP account</fullname>
      <gid>49</gid>
      <home>/srv/ftp</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>40</uid>
      <user_password>*</user_password>
      <username>ftp</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Gnome Display Manager daemon</fullname>
      <gid>111</gid>
      <home>/var/lib/gdm</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>106</uid>
      <user_password>*</user_password>
      <username>gdm</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Batch jobs daemon</fullname>
      <gid>25</gid>
      <home>/var/spool/atjobs</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>25</uid>
      <user_password>*</user_password>
      <username>at</username>
    </user>
    <user>
      <encrypted config:type="boolean">false</encrypted>
      <fullname>root</fullname>
      <gid>0</gid>
      <home>/root</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>0</uid>
      <user_password>%s</user_password>
      <username>root</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Mailer daemon</fullname>
      <gid>12</gid>
      <home>/var/spool/clientmqueue</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>8</uid>
      <user_password>*</user_password>
      <username>mail</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Daemon</fullname>
      <gid>2</gid>
      <home>/sbin</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>2</uid>
      <user_password>*</user_password>
      <username>daemon</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>NTP daemon</fullname>
      <gid>105</gid>
      <home>/var/lib/ntp</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>74</uid>
      <user_password>*</user_password>
      <username>ntp</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>User for D-Bus</fullname>
      <gid>101</gid>
      <home>/var/run/dbus</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>100</uid>
      <user_password>*</user_password>
      <username>messagebus</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Unix-to-Unix CoPy system</fullname>
      <gid>14</gid>
      <home>/etc/uucp</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>10</uid>
      <user_password>*</user_password>
      <username>uucp</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>User for haldaemon</fullname>
      <gid>102</gid>
      <home>/var/run/hald</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>101</uid>
      <user_password>*</user_password>
      <username>haldaemon</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>WWW daemon apache</fullname>
      <gid>8</gid>
      <home>/var/lib/wwwrun</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>30</uid>
      <user_password>*</user_password>
      <username>wwwrun</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>Manual pages viewer</fullname>
      <gid>62</gid>
      <home>/var/cache/man</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>13</uid>
      <user_password>*</user_password>
      <username>man</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>PolicyKit</fullname>
      <gid>106</gid>
      <home>/var/run/PolicyKit</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/bin/false</shell>
      <uid>103</uid>
      <user_password>*</user_password>
      <username>polkituser</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>News system</fullname>
      <gid>13</gid>
      <home>/etc/news</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max></max>
        <min></min>
        <warn></warn>
      </password_settings>
      <shell>/bin/bash</shell>
      <uid>9</uid>
      <user_password>*</user_password>
      <username>news</username>
    </user>
    <user>
      <fullname>SSH daemon</fullname>
      <gid>65</gid>
      <home>/var/lib/sshd</home>
      <shell>/bin/false</shell>
      <uid>71</uid>
      <username>sshd</username>
    </user>
    <user>
      <encrypted config:type="boolean">true</encrypted>
      <fullname>PulseAudio daemon</fullname>
      <gid>107</gid>
      <home>/var/lib/pulseaudio</home>
      <password_settings>
        <expire></expire>
        <flag></flag>
        <inact></inact>
        <max>99999</max>
        <min>0</min>
        <warn>7</warn>
      </password_settings>
      <shell>/sbin/nologin</shell>
      <uid>104</uid>
      <user_password>*</user_password>
      <username>pulse</username>
    </user>
  </users>
  <scripts>
    <chroot-scripts config:type="list"/>
    <post-scripts config:type="list"/>
    <pre-scripts config:type="list"/>
    <init-scripts config:type="list">
      <script>
        <filename>post.sh</filename>
        <interpreter>shell</interpreter>
        <source><![CDATA[
#!/bin/sh

echo ulimit -c unlimited >> /etc/profile.local
%s
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s
%s
%s
]]>
        </source>
      </script>
    </init-scripts>
  </scripts>
  <x11>
    <color_depth config:type="integer">4</color_depth>
    <display_manager>gdm</display_manager>
    <enable_3d config:type="boolean">false</enable_3d>
    <monitor>
      <display>
        <max_hsync config:type="integer">42</max_hsync>
        <max_vsync config:type="integer">72</max_vsync>
        <min_hsync config:type="integer">30</min_hsync>
        <min_vsync config:type="integer">50</min_vsync>
      </display>
      <monitor_device>Unknown</monitor_device>
      <monitor_vendor>Unknown</monitor_vendor>
    </monitor>
    <resolution>640x480 (VGA)</resolution>
    <window_manager>gnome</window_manager>
  </x11>
</profile>
""" %   (self.mainDisk,
         self.mainDisk,
         self.mainDisk,
         self.ethDevice,
         self.mainDisk,
         diffSLES[0],
         self._timezone(),
         self._password(),
         diffSLES[1],
         self.signalDir,         
         self._postInstall(),
         diffSLES[2],
         diffSLES[3]
         )  
        return ks
    def _generateSLES94(self):
        ks="""<?xml version="1.0"?>
<!DOCTYPE profile SYSTEM "/usr/share/autoinstall/dtd/profile.dtd">
<profile xmlns="http://www.suse.com/1.0/yast2ns" xmlns:config="http://www.suse.com/1.0/configns">
  <configure>
    <networking>
      <dns>
        <dhcp_hostname config:type="boolean">false</dhcp_hostname>
        <dhcp_resolv config:type="boolean">false</dhcp_resolv>
      </dns>
      <routing>
        <ip_forward config:type="boolean">false</ip_forward>
      </routing>
      <interfaces config:type="list">
        <interface>
          <bootproto>dhcp</bootproto>
          <device>%s</device>        
          <startmode>onboot</startmode>
        </interface>
      </interfaces>
    </networking>
    <printer>
      <cups_installation config:type="symbol">server</cups_installation>
      <default></default>
      <printcap config:type="list"/>
      <server_hostname></server_hostname>
      <spooler>cups</spooler>
    </printer>
    <runlevel>
      <default>3</default>
    </runlevel>
    <security>
      <console_shutdown>reboot</console_shutdown>
      <cracklib_dict_path>/usr/lib/cracklib_dict</cracklib_dict_path>
      <cwd_in_root_path>no</cwd_in_root_path>
      <cwd_in_user_path>no</cwd_in_user_path>
      <displaymanager_remote_access>no</displaymanager_remote_access>
      <enable_sysrq>no</enable_sysrq>
      <fail_delay>3</fail_delay>
      <faillog_enab>yes</faillog_enab>
      <gid_max>60000</gid_max>
      <gid_min>1000</gid_min>
      <kdm_shutdown>auto</kdm_shutdown>
      <lastlog_enab>yes</lastlog_enab>
      <obscure_checks_enab>yes</obscure_checks_enab>
      <pass_max_days>99999</pass_max_days>
      <pass_max_len>8</pass_max_len>
      <pass_min_days>0</pass_min_days>
      <pass_min_len>5</pass_min_len>
      <pass_warn_age>7</pass_warn_age>
      <passwd_encryption>des</passwd_encryption>
      <passwd_use_cracklib>yes</passwd_use_cracklib>
      <permission_security>easy</permission_security>
      <run_updatedb_as>nobody</run_updatedb_as>
      <system_gid_max>499</system_gid_max>
      <system_gid_min>100</system_gid_min>
      <system_uid_max>499</system_uid_max>
      <system_uid_min>100</system_uid_min>
      <uid_max>60000</uid_max>
      <uid_min>1000</uid_min>
      <useradd_cmd>/usr/sbin/useradd.local</useradd_cmd>
      <userdel_postcmd>/usr/sbin/userdel-post.local</userdel_postcmd>
      <userdel_precmd>/usr/sbin/userdel-pre.local</userdel_precmd>
    </security>
    <sound>
      <configure_detected config:type="boolean">false</configure_detected>
      <modules_conf config:type="list"/>
      <rc_vars/>
      <volume_settings config:type="list"/>
    </sound>
    <users config:type="list">
      <user>
        <encrypted config:type="boolean">false</encrypted>
        <user_password>%s</user_password>
        <username>root</username>
      </user>
    </users>
    <scripts>
      <chroot-scripts config:type="list"/>      
      <post-scripts config:type="list"/>
      <pre-scripts config:type="list"/>      
      <init-scripts config:type="list">
        <script>
          <filename>post.sh</filename>
          <interpreter>shell</interpreter> 
          <source><![CDATA[
#!/bin/sh

mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s
sleep 120
%s
]]>
          </source>
        </script>
      </init-scripts>
    </scripts>
  </configure>
  <install>
    <bootloader>
      <activate config:type="boolean">true</activate>
      <device_map config:type="list">
        <device_map_entry>
          <firmware>(hd0)</firmware>
          <linux>/dev/%s</linux>
        </device_map_entry>
      </device_map>
      <global config:type="list">
        <global_entry>
          <key>color</key>
          <value>white/blue black/light-gray</value>
        </global_entry>
        <global_entry>
          <key>default</key>
          <value>0</value>
        </global_entry>
        <global_entry>
          <key>timeout</key>
          <value>5</value>
        </global_entry>
      </global>
      <loader_device>/dev/%s</loader_device>
      <loader_type>grub</loader_type>
      <location>mbr</location>
      <repl_mbr config:type="boolean">true</repl_mbr>
      <sections config:type="list">
        <section config:type="list">
          <section_entry>
            <key>title</key>
            <value>Linux</value>
          </section_entry>
          <section_entry>
            <key>root</key>
            <value>(hd0,0)</value>
          </section_entry>
          <section_entry>
            <key>kernel</key>
            <value>/boot/vmlinuz root=/dev/%s2 selinux=0 serial console=ttyS0,115200 load_ramdisk=1 splash=silent showopts elevator=cfq</value>
          </section_entry>
          <section_entry>
            <key>initrd</key>
            <value>/boot/initrd</value>
          </section_entry>
        </section>
      </sections>
    </bootloader>
    <general>
      <clock>
        <hwclock>localtime</hwclock>
        <timezone>%s</timezone>
      </clock>
      <keyboard>
        <keymap>english-uk</keymap>
      </keyboard>
      <language>en_GB</language>
      <mode>
        <confirm config:type="boolean">false</confirm>
        <forceboot config:type="boolean">false</forceboot>
      </mode>
      <mouse>
        <id>none</id>
      </mouse>
      <signature-handling>
        <accept_verification_failed config:type="boolean">true</accept_verification_failed>
        <accept_file_without_checksum config:type="boolean">true</accept_file_without_checksum> 
      </signature-handling>  
    </general>
    <partitioning config:type="list">
      <drive>
        <device>/dev/%s</device>
        <initialize config:type="boolean">false</initialize>
        <partitions config:type="list">
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/boot</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>%sM</size>
          </partition>
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>7G</size>
          </partition>
        </partitions>
        <use>all</use>
      </drive>
    </partitioning>
    <software>
      <base>Minimal</base>
      <addons config:type="list">
        <addon>Basis-Devel</addon>
      </addons>
      <packages config:type="list">
        <package>wget</package>
        <package>python</package>
      </packages>
    </software>
  </install>
</profile>
""" % (self.ethDevice,
       self._password(),
       self.signalDir,
       self._postInstall(),
       self._rebootAfterInstall(),
       self.mainDisk,
       self.mainDisk,
       self.mainDisk,
       self._timezone(),
       self.mainDisk,
       self._bootDiskSize()
       )
        return ks
        
    def _generateStandard(self):
        ks="""<?xml version="1.0"?>
<!DOCTYPE profile SYSTEM "/usr/share/autoinstall/dtd/profile.dtd">
<profile xmlns="http://www.suse.com/1.0/yast2ns" xmlns:config="http://www.suse.com/1.0/configns">
  <configure>
    <networking>
      <dns>
        <dhcp_hostname config:type="boolean">false</dhcp_hostname>
        <dhcp_resolv config:type="boolean">false</dhcp_resolv>
      </dns>
      <routing>
        <ip_forward config:type="boolean">false</ip_forward>
      </routing>
      <interfaces config:type="list">
        <interface>
          <bootproto>dhcp</bootproto>
          <device>%s</device>        
          <startmode>onboot</startmode>
        </interface>
      </interfaces>
    </networking>
    <printer>
      <cups_installation config:type="symbol">server</cups_installation>
      <default></default>
      <printcap config:type="list"/>
      <server_hostname></server_hostname>
      <spooler>cups</spooler>
    </printer>
    <runlevel>
      <default>3</default>
    </runlevel>
    <security>
      <console_shutdown>reboot</console_shutdown>
      <cracklib_dict_path>/usr/lib/cracklib_dict</cracklib_dict_path>
      <cwd_in_root_path>no</cwd_in_root_path>
      <cwd_in_user_path>no</cwd_in_user_path>
      <displaymanager_remote_access>no</displaymanager_remote_access>
      <enable_sysrq>no</enable_sysrq>
      <fail_delay>3</fail_delay>
      <faillog_enab>yes</faillog_enab>
      <gid_max>60000</gid_max>
      <gid_min>1000</gid_min>
      <kdm_shutdown>auto</kdm_shutdown>
      <lastlog_enab>yes</lastlog_enab>
      <obscure_checks_enab>yes</obscure_checks_enab>
      <pass_max_days>99999</pass_max_days>
      <pass_max_len>8</pass_max_len>
      <pass_min_days>0</pass_min_days>
      <pass_min_len>5</pass_min_len>
      <pass_warn_age>7</pass_warn_age>
      <passwd_encryption>des</passwd_encryption>
      <passwd_use_cracklib>yes</passwd_use_cracklib>
      <permission_security>easy</permission_security>
      <run_updatedb_as>nobody</run_updatedb_as>
      <system_gid_max>499</system_gid_max>
      <system_gid_min>100</system_gid_min>
      <system_uid_max>499</system_uid_max>
      <system_uid_min>100</system_uid_min>
      <uid_max>60000</uid_max>
      <uid_min>1000</uid_min>
      <useradd_cmd>/usr/sbin/useradd.local</useradd_cmd>
      <userdel_postcmd>/usr/sbin/userdel-post.local</userdel_postcmd>
      <userdel_precmd>/usr/sbin/userdel-pre.local</userdel_precmd>
    </security>
    <sound>
      <configure_detected config:type="boolean">false</configure_detected>
      <modules_conf config:type="list"/>
      <rc_vars/>
      <volume_settings config:type="list"/>
    </sound>
    <users config:type="list">
      <user>
        <encrypted config:type="boolean">false</encrypted>
        <user_password>%s</user_password>
        <username>root</username>
      </user>
    </users>
    <scripts>
      <chroot-scripts config:type="list"/>      
      <post-scripts config:type="list"/>
      <pre-scripts config:type="list"/>      
      <init-scripts config:type="list">
        <script>
          <filename>post.sh</filename>
          <interpreter>shell</interpreter> 
          <source><![CDATA[
#!/bin/sh

mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
%s
sleep 120
%s
]]>
          </source>
        </script>
      </init-scripts>
    </scripts>
  </configure>
  <install>
    <bootloader>
      <activate config:type="boolean">true</activate>
      <device_map config:type="list">
        <device_map_entry>
          <firmware>(hd0)</firmware>
          <linux>/dev/%s</linux>
        </device_map_entry>
      </device_map>
      <global config:type="list">
        <global_entry>
          <key>color</key>
          <value>white/blue black/light-gray</value>
        </global_entry>
        <global_entry>
          <key>default</key>
          <value>0</value>
        </global_entry>
        <global_entry>
          <key>timeout</key>
          <value>5</value>
        </global_entry>
      </global>
      <loader_device>/dev/%s</loader_device>
      <loader_type>grub</loader_type>
      <location>mbr</location>
      <repl_mbr config:type="boolean">true</repl_mbr>
      <sections config:type="list">
        <section config:type="list">
          <section_entry>
            <key>title</key>
            <value>Linux</value>
          </section_entry>
          <section_entry>
            <key>root</key>
            <value>(hd0,0)</value>
          </section_entry>
          <section_entry>
            <key>kernel</key>
            <value>/boot/vmlinuz root=/dev/%s2 selinux=0 serial console=ttyS0,115200 load_ramdisk=1 splash=silent showopts elevator=cfq</value>
          </section_entry>
          <section_entry>
            <key>initrd</key>
            <value>/boot/initrd</value>
          </section_entry>
        </section>
      </sections>
    </bootloader>
    <general>
      <clock>
        <hwclock>localtime</hwclock>
        <timezone>%s</timezone>
      </clock>
      <keyboard>
        <keymap>english-uk</keymap>
      </keyboard>
      <language>en_GB</language>
      <mode>
        <confirm config:type="boolean">false</confirm>
        <forceboot config:type="boolean">false</forceboot>
      </mode>
      <mouse>
        <id>none</id>
      </mouse>
      <signature-handling>
        <accept_verification_failed config:type="boolean">true</accept_verification_failed>
        <accept_file_without_checksum config:type="boolean">true</accept_file_without_checksum> 
      </signature-handling>  
    </general>
    <partitioning config:type="list">
      <drive>
        <device>/dev/%s</device>
        <initialize config:type="boolean">false</initialize>
        <partitions config:type="list">
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/boot</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>%sM</size>
          </partition>
          <partition>
            <filesystem config:type="symbol">ext2</filesystem>
            <format config:type="boolean">true</format>
            <loop_fs config:type="boolean">false</loop_fs>
            <mount>/</mount>
            <partition_id config:type="integer">131</partition_id>
            <partition_type>primary</partition_type>
            <size>7G</size>
          </partition>
        </partitions>
        <use>all</use>
      </drive>
    </partitioning>
    <software>
      <patterns config:type="list">
        <pattern>base</pattern>
        <pattern>Basis-Devel</pattern>
      </patterns>
    </software>
  </install>
</profile>
""" % (self.ethDevice,
       self._password(),
       self.signalDir,
       self._postInstall(),
       self._rebootAfterInstall(),
       self.mainDisk,
       self.mainDisk,
       self.mainDisk,
       self._timezone(),
       self.mainDisk,
       self._bootDiskSize()
       )
        return ks
        
class DebianPreseedFile(object):
    def __init__(self,
                 distro,
                 repository,
                 filename,
                 installOn=xenrt.HypervisorType.native,
                 method="HTTP",
                 ethDevice="eth0",
                 password=None,
                 extraPackages=None,
                 ossVG=False,
                 arch="x86-32",
                 timezone=None,
                 postscript=None,
                 poweroff=True,
                 disk=None):
        self.filename=filename
        self.distro = distro
        self.repository = repository
        self.password=password
        self.method = method
        self.installOn = installOn
        self.ethDevice=ethDevice
        self.extraPackages = extraPackages
        self.ossVG = ossVG
        self.arch=arch
        self.postscript = postscript
        self.poweroff = poweroff
        self.disk = disk
        
    def generate(self):
        if self.distro.startswith("debian") and not self.distro.startswith("debian50"):
            ps=self.generateDebian()
        elif self.distro.startswith("ubuntu"):
            ps=self.generateUbuntu()
        else :
            ps=self.generateDebian5()
        
        if self.postscript:
            ps += '\n-d-i preseed/late_command string wget -q -O - %s | chroot /target /bin/bash' % (self.postscript)

        f=file(self.filename,"w")
        f.write(ps)
        f.close()
        
    def _distroName(self):
        if self.distro.startswith("debian60"):
            return "squeeze"
        elif self.distro.startswith("debian70"):
            return "wheezy" 
        elif self.distro.startswith("debian80"):
            return "jessie" 
        elif self.distro.startswith("debiantesting"):
            return "jessie" 
    
    def _password(self):
        if not self.password:
            self.password = xenrt.TEC().lookup("ROOT_PASSWORD")
        return crypt.crypt(self.password, "$1$Ojc.XG/d$Gdw9NG7.p9MihzRrhGr2s/")  
        
    def _timezone(self):
        deftz="UTC"
        return xenrt.TEC().lookup("OPTION_CARBON_TZ", deftz)
        
    def _rootPassClear(self):
        if not self.password:
            self.password=xenrt.TEC().lookup("ROOT_PASSWORD")
        return self.password
        
    def _mirror(self):
        self.httphost=""
        self.httppath=""

        if self.repository != "cdrom":
            r = re.search("http://([^/]+)(/.+)", self.repository)
            if not r:
                raise xenrt.XRTError("Could not parse repository into server/path",self.repository)
            
            self.httphost = r.group(1)
            self.httppath = r.group(2)

            if self.distro == "ubuntu1004":
                self.httppath = "/ubuntu"
            
            if not self.httppath.endswith("/"):
                self.httppath += "/"
                    
            Mirror = """

d-i    mirror/country           string manual
d-i    mirror/http/hostname     string %s
d-i    mirror/http/directory    string %s
d-i    apt-setup/security_host  string %s
d-i    apt-setup/security_path  string %s""" % (self.httphost,self.httppath, self.httphost,self.httppath)
            
        else:
            Mirror = "d-i mirror/file/directory string /cdrom"
        
        return Mirror

    def _disk(self):
        if self.disk:
            return "d-i     partman-auto/disk                       string %s" % (self.disk)
        return ""

    def _grubDisk(self):
        if self.disk:
            return "d-i     grub-installer/only_debian              boolean false\nd-i     grub-installer/bootdev                  string %s" % (self.disk)
        return "d-i     grub-installer/only_debian              boolean true"
            
    def generateDebian(self):
        """Generates Debian Preseed file for Debian6,Debian7,Debian7(x64)"""
        squeeze=["","tasksel tasksel/first                           multiselect standard"]
        wheezy=["d-i base-installer/install-recommends boolean false",
                "tasksel tasksel/first   multiselect standard"]
        jessie=["d-i base-installer/install-recommends boolean false",
                "tasksel tasksel/first   multiselect standard"]
        if self.distro.startswith("debian60"):
            subs=squeeze
            st=""
        elif self.distro.startswith("debian80") or self.distro.startswith("debiantesting"):
            subs=jessie
            st="d-i preseed/late_command string sed -i 's/PermitRootLogin without-password/PermitRootLogin yes/g' /target/etc/ssh/sshd_config; /target/etc/init.d/ssh restart;"
            if not self.disk:
                # Debian jessie enumerates the disks in the installer as xvda (on Xen) in 64-bit, but sda in 32-bit
                if "64" in self.arch and self.installOn==xenrt.HypervisorType.xen:
                    self.disk = "/dev/xvda"
                else:
                    self.disk = "/dev/sda"
                    # Workaround for bootloader issue
                    if self.distro.startswith("debiantesting"):
                        st += " sed -i 's/sda/xvda/g' /target/boot/grub/grub.cfg;"
        else:
            subs=wheezy
            if self.distro.startswith("debian70") and "64" in self.arch:
                st=""
            else:
                st="d-i     base-installer/kernel/image             string linux-generic-pae"
                    
        po = ""
        if self.poweroff:
            po = "d-i     debian-installer/exit/poweroff          boolean true"

        pstring="""d-i     debian-installer/locale                 string en_GB
d-i     debian-installer/allow_unauthenticated  string true
d-i     console-keymaps-at/keymap               select us
d-i     keyboard-configuration/xkb-keymap       select us
d-i     mirror/country                          string enter information manually
%s
d-i     mirror/http/proxy                       string 
d-i     mirror/udeb/suite                       string %s
d-i     mirror/suite                            string %s
d-i     time/zone string                        string %s

%s
d-i     partman-auto/method                     string regular
d-i     partman-auto/choose_recipe              select atomic
d-i     partman-lvm/device_remove_lvm           boolean true
d-i     partman/confirm_nooverwrite             boolean true
d-i     partman/confirm_write_new_label         boolean true
d-i     partman/choose_partition                select Finish partitioning and write changes to disk
d-i     partman/confirm                         boolean true
d-i     passwd/make-user                        boolean false
d-i     passwd/root-password-crypted            password %s
d-i     pkgsel/include                          string openssh-server psmisc ntpdate
%s
d-i     finish-install/reboot_in_progress       note
%s
d-i     apt-setup/services-select               multiselect none
%s
%s
popularity-contest                              popularity-contest/participate boolean false
%s
""" % (self._mirror(),
       self._distroName(),
       self._distroName(),
       self._timezone(),
       self._disk(),
       self._password(),
       self._grubDisk(),
       po,
       st,
       subs[0],
       subs[1])
        return pstring
        
    def generateDebian5(self):
        pstring="""d-i    debian-installer/locale         string en_GB
d-i    console-keymaps-at/keymap    select us
d-i    mirror/country            string enter information manually
%s
d-i    mirror/http/proxy        string 
d-i    debian-installer/allow_unauthenticated    string true
#d-i    anna/no_kernel_modules        boolean true
d-i    time/zone string        string %s
d-i    partman-auto/method        string regular
d-i    partman-auto/choose_recipe \
        select All files in one partition (recommended for new users)
d-i    partman/confirm_write_new_label    boolean true
d-i    partman/choose_partition \
        select Finish partitioning and write changes to disk
d-i    partman/confirm            boolean true
d-i    passwd/make-user        boolean false
d-i    passwd/root-password-crypted    password %s
popularity-contest    popularity-contest/participate    boolean    false
tasksel    tasksel/first            multiselect standard
d-i pkgsel/include string openssh-server psmisc
d-i    mirror/udeb/suite        string lenny
d-i    mirror/suite            string lenny
#d-i    mirror/udeb/suite        string sid
#d-i    mirror/suite            string sid
d-i    grub-installer/only_debian    boolean true
d-i    finish-install/reboot_in_progress    note
d-i    debian-installer/exit/poweroff    boolean true
#d-i    debian-installer/exit/always_halt boolean true
d-i apt-setup/services-select multiselect none
""" % (self._mirror(),
       self._timezone(),
       self._password()
       )
       
        return pstring
               
    def generateUbuntu(self):
        """Generating DebPreseed file for Ubuntu1204,Ubuntu1204-64,Ubuntu1004"""
        ubuntu1004=["d-i     mirror/country                  string enter information manually",
                    ""]
        ubuntu1264=["",""]
        ubuntu1204=["",
                   "d-i     base-installer/kernel/image string linux-generic-pae"]
        ubuntu1404 = ["",
                      "d-i preseed/late_command string sed -i 's/PermitRootLogin without-password/PermitRootLogin yes/g' /target/etc/ssh/sshd_config; /target/etc/init.d/ssh restart;"]
        if self.distro.startswith("ubuntu1004"):
            st=ubuntu1004
        elif self.distro.startswith("ubuntu1204") and "64" in self.arch:
            st=ubuntu1264
        elif self.distro.startswith("ubuntu1404"):
            st = ubuntu1404
        elif self.distro.startswith("ubuntudevel"):
            st = ubuntu1404
        else:
            st=ubuntu1204                
        
        pstring="""d-i    debian-installer/locale         string en_US
d-i    console-keymaps-at/keymap    select us
d-i keyboard-configuration/xkb-keymap select us
d-i console-setup/ask_detect boolean false
d-i console-setup/layoutcode string us
d-i console-setup/modelcode string SKIP


d-i netcfg/choose_interface select eth0

%s
%s
d-i    mirror/http/proxy        string 
d-i    debian-installer/allow_unauthenticated    string true
d-i apt-setup/backports boolean false
d-i    time/zone string        string %s
d-i    partman-auto/method        string regular

d-i    partman-auto/choose_recipe select atomic
d-i partman/confirm_nooverwrite boolean true


d-i    partman/confirm_write_new_label    boolean true
d-i    partman/choose_partition \
        select Finish partitioning and write changes to disk
d-i    partman/confirm            boolean true
d-i    passwd/make-user        boolean false
d-i passwd/root-login boolean true
d-i passwd/root-password-crypted    password %s

popularity-contest    popularity-contest/participate    boolean    false
tasksel    tasksel/first            multiselect standard
d-i pkgsel/include string openssh-server psmisc patch build-essential flex bc python
d-i    grub-installer/only_debian    boolean true
d-i    finish-install/reboot_in_progress    note
d-i    debian-installer/exit/poweroff    boolean true
%s
""" % (st[0],
       self._mirror(),
       self._timezone(),
       self._password(),
      st[1]
       )
        return pstring













