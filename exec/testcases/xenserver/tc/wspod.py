#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for workspace pod features
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, os.path, json, random, xml.dom.minidom
import sys, traceback
import xenrt
from xenrt.lazylog import *

class TCStoragePCIPassthrough(xenrt.Testcase):
    def prepare(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()
        gname = args.get("guest")
        if gname:
            self.guest = self.getGuest(gname)
        else:
            self.guest = self.host.guests.values()[0]
        if "multipathing" in args:
            self.guest.setState("UP")
            self.guest.xmlrpcExec("Install-WindowsFeature -Name Multipath-IO", powershell=True)
            self.guest.reboot()
            self.guest.xmlrpcExec("Enable-MSDSMAutomaticClaim -BusType SAS", powershell=True)
        
        self.guest.setState("DOWN")

        pcipattern = args.get("pci", "LSI")
        pci = self.host.execdom0("lspci | grep '%s'" % pcipattern).splitlines()[0].split()[0]
        self.guest.paramSet("other-config:pci", "0/0000:%s" % pci)
        if "sendbioskey" in args:
            self.guest.special['sendbioskey'] = True
        self.guest.start()
