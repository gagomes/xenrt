#
# XenRT: Test harness for Xen and the XenServer product family
#
# Storage tests
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import sys, string, os.path, re, os, time
import xenrt, xenrt.lib.xenserver

class TCVMRebootTime(xenrt.TestCase):
    """Time vm-reboot of a null VM and compare across host reboots."""

    SAMPLES_PER_DATAPOINT = 50
    ITERATIONS_PER_HOST_REBOOT = 10
    HOST_REBOOTS = 25

    def prepare(self, arglist):
        self.vmuuid = None
        self.host = self.getDefaultHost()
        cli = self.host.getCLIInstance()
        self.sruuid = self.host.getLocalSR()
        vdiuuid = cli.execute("vdi-create",
                              "sr-uuid=%s name-label=NullVDI type=user "
                              "virtual-size=4GiB" % (self.sruuid)).strip()
        self.vmuuid = cli.execute("vm-install",
                                  "new-name-label=%s "
                                  "template=\"Other install media\"" %
                                  (xenrt.randomGuestName())).strip()
        device = cli.execute("vm-param-get",
                             "uuid=%s param-name=allowed-VBD-devices" %
                             (self.vmuuid)).split("; ")[0]
        vbd = cli.execute("vbd-create",
                          "vm-uuid=%s device=%s vdi-uuid=%s bootable=true "
                          "type=Disk mode=RW unpluggable=True" %
                          (self.vmuuid, device, vdiuuid))

        rebootscript = """#!/bin/bash
for (( i=0;i<%u;i++ )); do
    time xe vm-reboot uuid=%s --force
done
""" % (self.SAMPLES_PER_DATAPOINT, self.vmuuid)
        fn = xenrt.TEC().tempFile()
        f = file(fn, "w")
        f.write(rebootscript)
        f.close()
        sftp = self.host.sftpClient()
        try:
            sftp.copyTo(fn, "/root/rebooter.sh")
        finally:
            sftp.close()

    def run(self, arglist):        
        cli = self.host.getCLIInstance()
        results = []
        try:
            for hostbootcount in range(self.HOST_REBOOTS):
                xenrt.TEC().logdelimit("Host reboot iteration %u..." %
                                       (hostbootcount))
                if hostbootcount > 0:
                    self.host.reboot()
                cli.execute("vm-start", "uuid=%s" % (self.vmuuid))
                for iter in range(self.ITERATIONS_PER_HOST_REBOOT):
                    xenrt.TEC().logverbose(\
                        "About to run %u samples of vm-reboot of iteration "
                        "%u of host reboot %u" %
                        (self.SAMPLES_PER_DATAPOINT, iter, hostbootcount))
                    data = self.host.execdom0("/root/rebooter.sh")
                    times = [ float(s) + 60.0 * float(m) \
                              for m, s in re.findall("real\s+(\d+)m([\d+\.]+)s",
                                                     data) ]
                    if len(times) != self.SAMPLES_PER_DATAPOINT:
                        raise xenrt.XRTError(\
                            "vm-reboot run only contained %u/%u samples" %
                            (len(times), self.SAMPLES_PER_DATAPOINT))
                    mean = sum(times)/len(times)
                    lineariter = hostbootcount * self.ITERATIONS_PER_HOST_REBOOT \
                                 + iter
                    xenrt.TEC().logverbose("DATAPOINT %u %f" %
                                           (lineariter, mean))
                    results.append((self.host.getName(), lineariter, mean))
                cli.execute("vm-shutdown", "uuid=%s --force" % (self.vmuuid))
        finally:
            fn = "%s/reboottimes.txt" % (xenrt.TEC().getLogdir())
            f = file(fn, "w")
            try:
                for result in results:
                    f.write("%s\n" % (string.join(map(str, result))))
            finally:
                f.close()

    def postRun(self):
        if self.vmuuid and self.host:
            cli = self.host.getCLIInstance()
            try:
                cli.execute("vm-shutdown", "uuid=%s --force" % (self.vmuuid))
            except:
                pass
            cli.execute("vm-uninstall", "uuid=%s --force" % (self.vmuuid))
            
class TCVMRebootTimeTest(TCVMRebootTime):

    SAMPLES_PER_DATAPOINT = 50
    ITERATIONS_PER_HOST_REBOOT = 5
    HOST_REBOOTS = 1
    
