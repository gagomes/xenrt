#
# XenRT: Test harness for Xen and the XenServer product family
#
# Tests of in-guest upgrades
#
# Copyright (c) Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, time
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
