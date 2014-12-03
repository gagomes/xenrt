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

    def upgradelinux(self, g, cmd):
        retVal = 0
        for i in range (1,20) :
            retVal = g.execguest("%s" %cmd, timeout=7200 , retval = "code")
            if not retVal : 
                break

        if retVal:
            g.execguest("%s" %cmd, timeout=7200)

        xenrt.TEC().comment("Rebooting to complete the upgrade process")
        g.reboot()

class TCUbuntuUpgrade(TCLinuxUpgrade):

    UBUNTU_NAME_MAP = {"ubuntu1404": "trusty",
                       "ubuntu1204": "precise",
                       "ubuntu1004": "lucid" }

    def run(self, arglist=None):
        args = self.parseArgsKeyValue(arglist)
        g = self.getGuest(args['guest'])
        newDistro = args['upgradeto']
        ubuntuName = self.UBUNTU_NAME_MAP[newDistro]
        g.execguest("echo deb %s %s main restricted > /etc/apt/sources.list" % (xenrt.TEC().lookup(["RPM_SOURCE", newDistro, g.arch, "HTTP"]), ubuntuName))
        g.execguest("echo deb %s %s-updates main restricted >> /etc/apt/sources.list" % (xenrt.TEC().lookup(["RPM_SOURCE", newDistro, g.arch, "HTTP"]), ubuntuName))
        g.execguest("apt-get update")
        cmd = "/bin/echo -e 'Y\n' | apt-get -y --force-yes dist-upgrade"
        self.upgradelinux(g,cmd)

class TCCentosUpgrade(TCLinuxUpgrade):

    def run(self, arglist=None):
        args = self.parseArgsKeyValue(arglist)

        # Set up the base urls required for centos upgrade
        centOsurl = xenrt.TEC().lookup(["RPM_SOURCE","centos7","x86-64", "HTTP"])
        urlprefix  = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
        repoPath   = "/etc/yum.repos.d/upgrade.repo"
        baseUrl    = "%s/CentOS/dev.centos.org" % (urlprefix)
        fastRpm    = "%s/CentOS/mirror.centos.org/Packages/yum-plugin-fastestmirror-1.1.30-30.el6.noarch.rpm" % (urlprefix)
        yumRpm     = "%s/CentOS/mirror.centos.org/Packages/yum-3.2.29-60.el6.centos.noarch.rpm" % (urlprefix)
        g = self.getGuest(args['guest'])

        # Create the repo file for the upgrade
        g.execguest("echo '[upgrade]' > %s" % (repoPath))
        g.execguest("echo name'=upgrade' >> %s" % (repoPath))
        g.execguest("echo baseurl'='%s >> %s" % (baseUrl, repoPath))
        g.execguest("echo enabled'='1 >>  %s" % (repoPath))
        g.execguest("echo gpgcheck'='0 >> %s" % (repoPath))
        xenrt.TEC().comment("Repo Created")

        # replace yum packages before the preupgrade step
        [g.execguest("rpm -Uvh --replacepkgs %s" % pkg) for pkg in [fastRpm, yumRpm]]
        xenrt.TEC().comment("Replaced yum packages")

        # Install tools required for preupgrade
        [g.execguest("yum -y install %s" %tool) for tool in ['preupgrade-assistant-contents','redhat-upgrade-tool','preupgrade-assistant']]
        g.execguest("/bin/echo -e 'y\n' | preupg")
        xenrt.TEC().comment("Pre upgrade completed")

        # run the redhat-upgrade-tool to start the upgrade
        g.execguest("rpm --import %s/RPM-GPG-KEY-CentOS-7" %(centOsurl))
        cmd = "redhat-upgrade-tool --network 7.0 --force --instrepo %s" %(centOsurl)
        self.upgradelinux(g,cmd)

        releaseCentos = g.execguest("cat /etc/centos-release")
        if not re.search("CentOS\s+Linux\s+release\s+7" , releaseCentos) : raise xenrt.XRTError("Upgrade was not successful")
