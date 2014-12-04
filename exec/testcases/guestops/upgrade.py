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
import xenrt

class TCLinuxUpgrade(xenrt.TestCase):

    def run(self, arglist=None):
        self.args  = self.parseArgsKeyValue(arglist)
        self.guest = self.getGuest(self.args['guest'])

    def upgradelinux(self,cmd):
        retVal = 0
        for i in range (1,20) :
            retVal = self.guest.execguest("%s" %cmd, timeout=7200 , retval = "code")
            if not retVal : 
                break

        if retVal:
            self.guest.execguest("%s" %cmd, timeout=7200)

        xenrt.TEC().comment("Rebooting to complete the upgrade process")
        self.guest.reboot()

class TCUbuntuUpgrade(TCLinuxUpgrade):

    UBUNTU_NAME_MAP = {"ubuntu1404": "trusty",
                       "ubuntu1204": "precise",
                       "ubuntu1004": "lucid" }

    def run(self):

        newDistro = self.args['upgradeto']
        ubuntuName = self.UBUNTU_NAME_MAP[newDistro]
        self.guest.execguest("echo deb %s %s main restricted > /etc/apt/sources.list" % (xenrt.TEC().lookup(["RPM_SOURCE", newDistro, g.arch, "HTTP"]), ubuntuName))
        self.guest.execguest("echo deb %s %s-updates main restricted >> /etc/apt/sources.list" % (xenrt.TEC().lookup(["RPM_SOURCE", newDistro, g.arch, "HTTP"]), ubuntuName))
        self.guest.execguest("apt-get update")
        cmd = "/bin/echo -e 'Y\n' | apt-get -y --force-yes dist-upgrade"
        self.upgradelinux(cmd)

class TCCentosUpgrade(TCLinuxUpgrade):

    def run(self):
        # Set up the base urls required for centos upgrade
        centOsurl = xenrt.TEC().lookup(["RPM_SOURCE","centos7","x86-64", "HTTP"])
        urlPrefix  = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        repoPath   = "/etc/yum.repos.d/upgrade.repo"
        baseUrl    = "%s/CentOS/dev.centos.org" % (urlPrefix)
        fastRpm    = "%s/CentOS/mirror.centos.org/Packages/yum-plugin-fastestmirror-1.1.30-30.el6.noarch.rpm" % (urlPrefix)
        yumRpm     = "%s/CentOS/mirror.centos.org/Packages/yum-3.2.29-60.el6.centos.noarch.rpm" % (urlPrefix)

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
        [self.guest.execguest("yum -y install --assumeyes %s" %tool) for tool in ['preupgrade-assistant-contents','redhat-upgrade-tool','preupgrade-assistant', 'preupg']]
        xenrt.TEC().comment("Pre upgrade completed")

        # run the redhat-upgrade-tool to start the upgrade
        self.guest.execguest("rpm --import %s/RPM-GPG-KEY-CentOS-7" %(centOsurl))
        cmd = "redhat-upgrade-tool --network 7.0 --force --instrepo %s" %(centOsurl)
        self.upgradelinux(cmd)

        releaseCentos = self.guest.execguest("cat /etc/centos-release")
        if not re.search("CentOS\s+Linux\s+release\s+7" , releaseCentos) : raise xenrt.XRTError("Upgrade was not successful")

class TCOelUpgrade(TCLinuxUpgrade):

    def run(self):
        urlPrefix  = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        # Set up the base urls required for oel upgrade
        baseUrl    = "%s/Oel/public-yum.oracle.com/repo/OracleLinux/OL6/addons/x86_64" % (urlPrefix)
        repoPath   = "/etc/yum.repos.d/upgrade.repo"
        fastRpm    = "%s/CentOS/mirror.centos.org/Packages/yum-plugin-fastestmirror-1.1.30-30.el6.noarch.rpm" % (urlPrefix)
        yumRpm     = "%s/CentOS/mirror.centos.org/Packages/yum-3.2.29-60.el6.centos.noarch.rpm" % (urlPrefix)
        oel7Url    = xenrt.TEC().lookup(["RPM_SOURCE","oel7","x86-64", "HTTP"])

        # Create the repo file for the upgrade
        self.guest.execguest("echo '[upgrade]' > %s" % (repoPath))
        self.guset.execguest("echo name'=upgrade' >> %s" % (repoPath))
        self.guset.execguest("echo baseurl'='%s >> %s" % (baseUrl, repoPath))
        self.guest.execguest("echo gpgkey'=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-oracle' >> %s" %(repoPath))
        self.guest.execguest("echo gpgcheck'='1 >> %s" % (repoPath))
        self.guest.execguest("echo enabled'='1 >>  %s" % (repoPath))
        xenrt.TEC().comment("Repo Created")

        # replace yum packages before the preupgrade step
        [self.guest.execguest("rpm -Uvh --replacepkgs %s" % pkg) for pkg in [fastRpm, yumRpm]]
        xenrt.TEC().comment("Replaced yum packages")

        # Install tools required for preupgrade
        [self.guest.execguest("yum -y install --assumeyes %s" %tool) for tool in ['openscap','preupgrade-assistant-contents','redhat-upgrade-tool','preupg']]
        xenrt.TEC().comment("Pre upgrade completed")

        # run the redhat-upgrade-tool to start the upgrade
        cmd = "redhat-upgrade-tool --network 7.0 --force --instrepo %s" %(oel7Url)
        self.upgradelinux(cmd)

        releaseOel = self.guest.execguest("cat /etc/centos-release")
        if not re.search("Oracle\s+Linux\s+Server\s+release\s+7" , releaseOel) : raise xenrt.XRTError("Upgrade was not successful")
