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

class TCUbuntuUpgrade(xenrt.TestCase):

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
        maxattempts = 20
        success = False
        i = 0
        while i < maxattempts:
            try:
                g.execguest("/bin/echo -e \"Y\\n\" | apt-get -y --force-yes dist-upgrade", timeout=7200)
                success = True
                break
            except:
                i += 1
        if not success:
            g.execguest("/bin/echo -e \"Y\\n\" | apt-get -y --force-yes dist-upgrade", timeout=7200)

        g.reboot()

class TCCentosUpgrade(xenrt.TestCase):

    repoPath   = "/etc/yum.repos.d/upgrade.repo"
    urlprefix  = xenrt.TEC().lookup("EXPORT_DISTFILES_HTTP", "")
    baseUrl    = "%s/CentOS/dev.centos.org" % (urlprefix)
    fastRpm    = "%s/CentOS/mirror.centos.org/Packages/yum-plugin-fastestmirror-1.1.30-30.el6.noarch.rpm" % (urlprefix)
    yumRpm     = "%s/CentOS/mirror.centos.org/Packages/yum-3.2.29-60.el6.centos.noarch.rpm" % (urlprefix)
    upgradeRpm = "%s/CentOS/centos.excellmedia.net/RPM-GPG-KEY-CentOS-7" % (urlprefix)
    instRepo   = "%s/CentOS/centos.excellmedia.net/" % (urlprefix)

    def run(self, arglist=None):
        args = self.parseArgsKeyValue(arglist)
        g = self.getGuest(args['guest'])
        g.execguest("echo \[upgrade\] > %s" % (self.repoPath))
        g.execguest("echo name\=upgrade >> %s" % (self.repoPath))
        g.execguest("echo baseurl\=%s >> %s" % (self.baseUrl, self.repoPath))
        g.execguest("echo enabled\=1 >>  %s" % (self.repoPath))
        g.execguest("echo gpgcheck\=0 >> %s" % (self.repoPath))
        xenrt.TEC().comment("Repo Created")
        g.execguest("yum -y install preupgrade-assistant-contents")

        try :
            g.execguest("rpm -Uvh --replacepkgs %s" %(self.fastRpm))
            g.execguest("rpm -Uvh --replacepkgs %s" %(self.yumRpm))
            xenrt.TEC().comment("Replaced yum packages")
            g.execguest("yum -y install redhat-upgrade-tool")
            g.execguest("yum -y install preupgrade-assistant")
            g.execguest("/bin/echo -e 'y\n' | preupg")
            xenrt.TEC().comment("Pre upgrade completed")
        except:
            raise xenrt.XRTError("Pre upgrade failed")

        maxattempts = 20
        success = False
        i = 0
        while i < maxattempts:
            try :
                g.execguest("rpm --import %s" %(self.upgradeRpm))
                g.execguest("redhat-upgrade-tool --network 7.0 --force --instrepo %s" %(self.instRepo), timeout=7200)
                xenrt.TEC().comment("Red hat upgrade tool completed")
                success = True
                break
            except :
                i += 1
        if not success:
            raise xenrt.XRTError("Upgrade failed after multiple attempts")

        g.reboot()

        releaseCentos = g.execguest("cat /etc/centos-release")
        if not re.search("7" , releaseCentos) : raise xenrt.XRTError("Upgrade was not successful")
