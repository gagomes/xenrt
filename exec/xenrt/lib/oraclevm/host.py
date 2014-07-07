#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a Hyper-V host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, urllib, os.path, crypt

import xenrt


__all__ = ["createHost",
           "OracleVMHost"]

def createHost(id=0,
               version=None,
               pool=None,
               name=None,
               dhcp=True,
               license=True,
               diskid=0,
               diskCount=1,
               productType=None,
               productVersion=None,
               withisos=False,
               noisos=None,
               overlay=None,
               installSRType=None,
               suppackcds=None,
               addToLogCollectionList=False,
               noAutoPatch=False,
               disablefw=False,
               usev6testd=True,
               ipv6=None,
               noipv4=False,
               basicNetwork=True,
               extraConfig=None):

    machine = str("RESOURCE_HOST_%s" % (id))

    m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
    xenrt.GEC().startLogger(m)

    if not productVersion:
        productVersion = xenrt.TEC().lookup("ORACLEVM_VERSION", "3.2.8")

    host = OracleVMHost(m, productVersion=productVersion, productType=productType)

    host.install()

    xenrt.TEC().registry.hostPut(machine, host)
    xenrt.TEC().registry.hostPut(name, host)

    return host

class OracleVMHost(xenrt.GenericHost):

    def install(self):

        f = xenrt.TEC().getFile("/usr/groups/xenrt/oraclevm/%s/ovm.iso" % (self.productVersion))
        d = xenrt.NFSDirectory()
        m = xenrt.MountISO(f)
        d.copyIn("%s/*" % m.getMount())
        m.unmount()


        host, path = d.getHostAndPath("")

        pw = crypt.crypt(xenrt.TEC().lookup("ROOT_PASSWORD"), "Xa")

        ksd = xenrt.NFSDirectory()

        ks="""lang en_US
#langsupport en_US
eula Accepted
keyboard us
#mouse genericusb
timezone --utc America/Los_Angeles
rootpw --iscrypted %s
zerombr
bootloader --location=mbr
install
nfs --server %s --dir %s
clearpart --all
part /boot --fstype ext3 --size 512 --ondisk sda
part  swap --size 4096 --ondisk sda
part / --fstype ext3 --size 1 --grow --ondisk sda
network --bootproto dhcp --device eth0
ovsagent --iscrypted %s
ovsmgmntif eth0
auth  --useshadow  --enablemd5
firewall --disabled
#Do not configure the X Window System
skipx
text

%%packages
@Everything

%%pre
dd if=/dev/zero of=/dev/sda bs=1024 count=1024

%%post --nochroot

%%post
mkdir /tmp/xenrttmpmount
mount -onolock -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount

""" % (pw, host, path, pw, ksd.getMountURL(""))

        with open("%s/ks.cfg" % ksd.path(), "w") as f:
            f.write(ks)

        pxe = xenrt.PXEBoot()
        pxe.addEntry("local", boot="local")
        serport = self.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.lookup("SERIAL_CONSOLE_BAUD", "115200")
        comport = str(int(serport) + 1)

        if self.lookup("PXE_NO_SERIAL", False, boolean=True):
            pxe.setSerial(None,None)
        else:
            pxe.setSerial(serport, serbaud)

        chain = self.lookup("PXE_CHAIN_LOCAL_BOOT", None)
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")

        if self.productVersion.startswith("2"):
            pxe.copyIn("%s/images/pxeboot/vmlinuz" % d.path())
            pxe.copyIn("%s/images/pxeboot/initrd.img" % d.path())

            install = pxe.addEntry("ovminstall", boot="mboot")
            install.linuxSetKernel("%s/vmlinuz" % pxe.path())
            install.linuxArgsKernelAdd("initrd=%s" % install.cfg.makeBootPath("%s/initrd.img" % pxe.path()))
            install.linuxArgsKernelAdd("load_ramdisk=1")
            install.linuxArgsKernelAdd("network")
            install.linuxArgsKernelAdd("mem=32g")
            install.linuxArgsKernelAdd("console=ttyS0,115200")
            install.linuxArgsKernelAdd("ks=nfs:%sks.cfg" % ksd.getMountURL(""))
        else:
            pxe.copyIn("%s/isolinux/xen.gz" % d.path())
            pxe.copyIn("%s/isolinux/vmlinuz" % d.path())
            pxe.copyIn("%s/isolinux/initrd.img" % d.path())

            install = pxe.addEntry("ovminstall", boot="mboot")
            install.mbootSetKernel("%s/xen.gz" % pxe.path())
            install.mbootSetModule1("%s/vmlinuz" % pxe.path())
            install.mbootSetModule2("%s/initrd.img" % pxe.path())

            install.mbootArgsModule1Add("ks=nfs:%sks.cfg" % ksd.getMountURL(""))
            install.mbootArgsModule1Add("ksdevice=eth0")
            install.mbootArgsModule1Add("ip=dhcp")
            #install.mbootArgsKernelAdd("com%s=%s,8n1" % (comport, serbaud))
            #install.mbootArgsModule1Add("console=tty0")
            #install.mbootArgsModule1Add("console=ttyS%s,%sn8" % (serport, serbaud))
        pxe.setDefault("ovminstall")
        pxe.writeOut(self.machine)


        self.machine.powerctl.cycle()

        xenrt.waitForFile("%s/.xenrtsuccess" % ksd.path(), 3600, desc="Installer boot on !%s" % (self.getName()))
        xenrt.sleep(30)
        pxe.setDefault("local")
        pxe.writeOut(self.machine)
        self.machine.powerctl.cycle()

        self.waitForSSH(1800, desc="Host boot (!%s)" % (self.getName()))
         

