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
import testcases.benchmarks.workloads

class TCStoragePCIPassthrough(xenrt.TestCase):
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

        mylunid = int([self.host.lookup(["FC", x, 'LUNID']) for x in self.host.lookup("FC").keys() if not self.host.lookup(["FC", x, "SHARED"], True, boolean=True)][0])
        
        disks = json.loads(self.guest.xmlrpcExec(
            "Get-WmiObject -Class win32_diskdrive | Where {$_.SCSILogicalUnit -eq %d} | Select Name | ConvertTo-Json -Compress" % mylunid,
            powershell=True,
            returndata=True).strip().splitlines()[-1])
       

        mydisk = [re.search("PHYSICALDRIVE(\d+)", x['Name']).group(1) for x in disks if not x['Name'].endswith("PHYSICALDRIVE0")][0]

        self.guest.xmlrpcInitializeDisk(mydisk)
        self.guest.xmlrpcFormat("e", quick=True)
        self.fio = testcases.benchmarks.workloads.FIOWindows(self.guest, drive="e")
        self.fio.install()

    def run(self, arglist):
        self.fio.runCheck()

