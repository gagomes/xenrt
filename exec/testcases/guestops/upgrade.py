#
# XenRT: Test harness for Xen and the XenServer product family
#
# Tests of in-guest upgrades
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, time, re
from abc import ABCMeta, abstractmethod
import xenrt

class TCLinuxUpgrade(xenrt.TestCase, object):

    __metaclass__ = ABCMeta

    def prepare(self, arglist=None):
        self.urlPrefix  = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        self.args  = self.parseArgsKeyValue(arglist)
        self.guest = self.getGuest(self.args['guest'])

    def run(self, arglist=None):
        self.preconfigureGuest()
        self.upgradeLinux(self.upgradeCommand())
        self.checkUpgrade()

    def upgradeLinux(self,cmd):
        retVal = 0
        for i in range (1,20) :
            retVal = self.guest.execguest("%s" %cmd, timeout=7200 , retval = "code")
            if not retVal :
                break

        if retVal:
            self.guest.execguest("%s" %cmd, timeout=7200)

        xenrt.TEC().comment("Rebooting to complete the upgrade process")
        self.guest.reboot()

    @abstractmethod
    def preconfigureGuest(self):
        pass

    @abstractmethod
    def checkUpgrade(self):
        pass

    @abstractmethod
    def upgradeCommand(self):
        pass

class _TCDebianStyleUpgrade(TCLinuxUpgrade):

    DISTRO_NAME_MAP = {"ubuntu1404": ("trusty", "Ubuntu 14.04"),
                       "ubuntu1204": ("precise", "Ubuntu 12.04"),
                       "ubuntu1004": ("lucid", "Ubuntu 10.04"),
                       "debian60": ("squeeze", "Debian GNU/Linux 6"),
                       "debian70": ("wheezy", "Debian GNU/Linux 7"),
                       "debian80": ("jessie", "Debian GNU/Linux 8")}

    def preconfigureGuest(self):

        newDistro = self.args['upgradeto']
        distroName = self.DISTRO_NAME_MAP[newDistro][0]
        self.releaseName = self.DISTRO_NAME_MAP[newDistro][1]
        distroUrl  = xenrt.TEC().lookup(["RPM_SOURCE", newDistro, self.guest.arch, "HTTP"])
        sourceList = "/etc/apt/sources.list"

        self.configureSources(sourceList, distroUrl, distroName)

        self.guest.execguest("apt-get update")
        xenrt.TEC().comment("apt-get update completed")
        if self.args['upgradeto'] == "debian80":
            self.guest.execguest("apt-get -y --force-yes install libperl4-corelibs-perl")

    def upgradeCommand(self):
        return "/bin/echo -e 'Y\\n' | apt-get -y --force-yes -o Dpkg::Options::=\"--force-confdef\" -o Dpkg::Options::=\"--force-confold\" dist-upgrade"

    def checkUpgrade(self):
        distroRelease = self.guest.execguest("cat /etc/issue.net")
        if not re.search(self.releaseName, distroRelease) : raise xenrt.XRTError("Upgrade was not successful")

class TCUbuntuUpgrade(_TCDebianStyleUpgrade):

    def configureSources(self, sourceList, distroUrl, distroName):
        #replace the sources.list
        self.guest.execguest("echo deb %s %s main restricted universe multiverse > %s" % (distroUrl, distroName,sourceList ))
        self.guest.execguest("echo deb %s %s-updates main restricted universe multiverse >> %s" % (distroUrl, distroName, sourceList))

class TCDebianUpgrade(_TCDebianStyleUpgrade):
    def configureSources(self, sourceList, distroUrl, distroName):
        self.guest.execguest("echo deb %s %s main > %s" % (distroUrl, distroName,sourceList ))
        if self.guest.execguest("[ -e /etc/apt/sources.list.d/updates.list ]", retval="code") == 0 and xenrt.TEC().lookup("APT_SERVER", None):
                self.guest.execguest("echo deb %s/debsecurity %s/updates main > /etc/apt/sources.list.d/updates.list" % (xenrt.TEC().lookup("APT_SERVER"), distroName))
                self.guest.execguest("echo deb %s/debian %s-updates main >> /etc/apt/sources.list.d/updates.list" % (xenrt.TEC().lookup("APT_SERVER"), distroName))
            
        

class TCCentosUpgrade(TCLinuxUpgrade):

    def preconfigureGuest(self):
        fastRpm    = "%s/CentOS/mirror.centos.org/Packages/yum-plugin-fastestmirror-1.1.30-30.el6.noarch.rpm" % (self.urlPrefix)
        yumRpm     = "%s/CentOS/mirror.centos.org/Packages/yum-3.2.29-60.el6.centos.noarch.rpm" % (self.urlPrefix)
        repoPath   = "/etc/yum.repos.d/upgrade.repo"
        baseUrl    = "%s/CentOS/dev.centos.org" % (self.urlPrefix)

        # Create the repo file for the upgrade
        self.guest.execguest("echo '[upgrade]' > %s" % (repoPath))
        self.guest.execguest("echo name'=upgrade' >> %s" % (repoPath))
        self.guest.execguest("echo baseurl'='%s >> %s" % (baseUrl, repoPath))
        self.guest.execguest("echo enabled'='1 >>  %s" % (repoPath))
        self.guest.execguest("echo gpgcheck'='0 >> %s" % (repoPath))
        xenrt.TEC().comment("Repo Created")

        # replace yum packages before the preupgrade step
        [self.guest.execguest("rpm -Uvh --replacepkgs %s" % pkg) for pkg in [fastRpm, yumRpm]]
        xenrt.TEC().comment("Replaced yum packages")

        # Install tools required for preupgrade
        [self.guest.execguest("yum -y install --assumeyes %s" %tool) for tool in ['preupgrade-assistant-contents','redhat-upgrade-tool','preupgrade-assistant']]
        self.guest.execguest("/bin/echo -e 'y\n' | preupg")
        xenrt.TEC().comment("Pre upgrade completed")

    def upgradeCommand(self):
        centOsurl = xenrt.TEC().lookup(["RPM_SOURCE","centos7","x86-64", "HTTP"])
        #import the centos key
        self.guest.execguest("rpm --import %s/RPM-GPG-KEY-CentOS-7" %(centOsurl))
        return "redhat-upgrade-tool --network 7.0 --force --instrepo %s" %(centOsurl)

    def checkUpgrade(self):
        releaseCentos = self.guest.execguest("cat /etc/centos-release")
        if not re.search(r"^CentOS Linux release 7.0" , releaseCentos) : raise xenrt.XRTError("Upgrade was not successful")

class TCOelUpgrade(TCLinuxUpgrade):

    def preconfigureGuest(self):

        baseUrl    = "%s/Oel/public-yum.oracle.com/repo/OracleLinux/OL6/addons/x86_64" % (self.urlPrefix)
        fastRpm    = "%s/CentOS/mirror.centos.org/Packages/yum-plugin-fastestmirror-1.1.30-30.el6.noarch.rpm" % (self.urlPrefix)
        yumRpm     = "%s/CentOS/mirror.centos.org/Packages/yum-3.2.29-60.el6.centos.noarch.rpm" % (self.urlPrefix)
        repoPath   = "/etc/yum.repos.d/upgrade.repo"

        # Create the repo file for the upgrade
        self.guest.execguest("echo '[upgrade]' > %s" % (repoPath))
        self.guest.execguest("echo name'=upgrade' >> %s" % (repoPath))
        self.guest.execguest("echo baseurl'='%s >> %s" % (baseUrl, repoPath))
        self.guest.execguest("echo gpgkey'=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-oracle' >> %s" %(repoPath))
        self.guest.execguest("echo gpgcheck'='1 >> %s" % (repoPath))
        self.guest.execguest("echo enabled'='1 >>  %s" % (repoPath))
        xenrt.TEC().comment("Repo Created")

        # replace yum packages before the preupgrade step
        [self.guest.execguest("rpm -Uvh --replacepkgs %s" % pkg) for pkg in [fastRpm, yumRpm]]
        xenrt.TEC().comment("Replaced yum packages")

        # Install tools required for preupgrade
        [self.guest.execguest("yum -y install --assumeyes %s" %tool) for tool in ['openscap','preupgrade-assistant-contents','redhat-upgrade-tool']]
        self.guest.execguest("/bin/echo -e 'y\n' | preupg")
        xenrt.TEC().comment("Pre upgrade completed")

    def upgradeCommand(self):
        oel7Url    = xenrt.TEC().lookup(["RPM_SOURCE","oel7","x86-64", "HTTP"])
        return "redhat-upgrade-tool --network 7.0 --force --instrepo %s" %(oel7Url)

    def checkUpgrade(self):
        releaseOel = self.guest.execguest("cat /etc/oracle-release")
        if not re.search(r"^Oracle Linux Server release 7.0" , releaseOel) : raise xenrt.XRTError("Upgrade was not successful")
