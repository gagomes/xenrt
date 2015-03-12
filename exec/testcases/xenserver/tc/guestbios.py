#
# XenRT: Test harness for Xen and the XenServer product family
#
# Guest BIOS strings standalone testcases
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os, os.path
import xenrt, xenrt.lib.xenserver

CUSTOM_BIOS_STATUS  = "This VM is BIOS-customized."
GENERIC_BIOS_STATUS = "This VM is BIOS-generic."
NO_BIOS_STATUS      = "The BIOS strings of this VM have not yet been set."

BIOS_VENDOR          = "bios-vendor"
BIOS_VERSION         = "bios-version"
SYSTEM_MANUFACTURER  = "system-manufacturer"
SYSTEM_PRODUCT_NAME  = "system-product-name"
SYSTEM_VERSION       = "system-version"
SYSTEM_SERIAL_NUMBER = "system-serial-number"
HP_ROMBIOS           = "hp-rombios"

OEM_STRINGS          = "oem"
XENSTORE_OEM_PREFIX  = "oem-"
DMI_OEM_PREFIX       = "String"
OEM_1                = "Xen"
OEM_2                = "MS_VM_CERT/SHA1/bdbeb6e0a816d43fa6d3fe8aaef04c2bad9d3e3d"

XENSTORE_BIOS_STRINGS = [BIOS_VENDOR,
                        BIOS_VERSION,
                        SYSTEM_MANUFACTURER,
                        SYSTEM_PRODUCT_NAME,
                        SYSTEM_VERSION,
                        SYSTEM_SERIAL_NUMBER,
                        HP_ROMBIOS]

DMI_BIOS_STRINGS = [BIOS_VENDOR,
                    BIOS_VERSION,
                    SYSTEM_MANUFACTURER,
                    SYSTEM_PRODUCT_NAME,
                    SYSTEM_VERSION,
                    SYSTEM_SERIAL_NUMBER]

XENSTORE_GENERIC_BIOS = {BIOS_VENDOR: 'Xen',
                         BIOS_VERSION: '',
                         SYSTEM_MANUFACTURER: 'Xen',
                         SYSTEM_PRODUCT_NAME: 'HVM domU',
                         SYSTEM_VERSION: '',
                         SYSTEM_SERIAL_NUMBER: '',
                         HP_ROMBIOS: '',
                         OEM_STRINGS: [OEM_1, OEM_2]}

class TC10190(xenrt.TestCase):
    """Install a BIOS-customized Linux HVM VM, by copying the BIOS strings from the pool master"""

    MEMORY = 768 
    RAMDISK_SIZE = 550000

    def getXenStoreBIOS(self, domID, host):
        bios = {}

        # Get BIOS strings except the OEM Strings for the specified domain
        for xsString in XENSTORE_BIOS_STRINGS:
            bios[xsString] = host.xenstoreRead("/local/domain/%s/bios-strings/%s" %
                                               (domID, xsString))
        # Get the OEM Strings
        i = 1
        oemStrings = []
        while True:
            xsString = "%s%s" % (XENSTORE_OEM_PREFIX, i)
            try:
                oemStrings.append(host.xenstoreRead("/local/domain/%s/bios-strings/%s" %
                                                    (domID, xsString)))
            except:
                break
            i += 1
        bios[OEM_STRINGS] = oemStrings
        xenrt.TEC().logverbose("Guest XenStore BIOS Strings: %s" % (bios))
        return bios

    def getHPRomBios(self, target):
        script = """#!/usr/bin/python
import os
f = open('/dev/mem','r')
fd = f.fileno()
os.lseek(fd,0xfffea,0)
data = os.read(fd,6)
f.close()
print data
"""
        sftp = target.sftpClient()
        try:
            t = xenrt.TEC().tempFile()
            f = file(t, "w")
            f.write(script)
            f.close()
            sftp.copyTo(t, "/tmp/hprombios.py")
        finally:
            sftp.close()
        target.execcmd("chmod +x /tmp/hprombios.py")
        data = string.strip(target.execcmd("/tmp/hprombios.py"))
        if re.search("Traceback", data):
            raise xenrt.XRTFailure(data)
        xenrt.TEC().logverbose("Read hp_rombios from memory: %s" % (data))
        if data != "COMPAQ":
            return ""
        return data

    def getDMIBIOS(self, target):
        bios = {}

        # Get BIOS strings except OEM Strings and hp-rombios
        for dmiString in DMI_BIOS_STRINGS:
            bios[dmiString] = string.strip(
                               target.execcmd("dmidecode -s %s" % (dmiString)))
            # Some strings are "Not Specified". Map them to the empty string
            if bios[dmiString] == "Not Specified":
                bios[dmiString] = ""

        # Get the OEM Strings
        oemData = target.execcmd("dmidecode -t11 || true")
        oemData = target.execcmd("dmidecode -t11 | grep \"%s \" || true" % DMI_OEM_PREFIX)

        oemStrings = []
        # For hosts, set the first two OEM Strings to the standard values
        if isinstance(target, xenrt.objects.GenericHost):
            oemStrings = [OEM_1, OEM_2]

        for line in oemData.splitlines():
            r = re.search(r'String [0-9]+: (.*)', line)
            if not r:
                raise xenrt.XRTFailure("Could not parse dmidecode for OEM strings")
            oemStr = string.strip(r.group(1))
            if not isinstance(target, xenrt.objects.GenericHost) or oemStr:
                oemStrings.append(oemStr)
        bios[OEM_STRINGS] = oemStrings            

        # Get the hp-rombios
        bios[HP_ROMBIOS] = self.getHPRomBios(target)

        if isinstance(target, xenrt.objects.GenericHost):
            xenrt.TEC().logverbose("Host DMI BIOS Strings: %s" % (bios))
        else:
            xenrt.TEC().logverbose("Guest DMI BIOS Strings: %s" % (bios))
        return bios

    def getDMIGenericBIOS(self, xenVersion):
        # In DMI, the product sets BIOS_VERSION and SYSTEM_VERSION to the version
        # of Xen. Return a copy of XENSTORE_GENERIC_BIOS with those values set.
        dmiGenBIOS = XENSTORE_GENERIC_BIOS.copy()
        dmiGenBIOS[BIOS_VERSION] = xenVersion
        dmiGenBIOS[SYSTEM_VERSION] = xenVersion
        return dmiGenBIOS

    def checkGuestXenStoreBIOS(self, guestxsBIOS, expectedBIOS):
        diffBIOS = []
        # Compare all values except OEM Strings
        for biosString in XENSTORE_BIOS_STRINGS:
            if guestxsBIOS[biosString] != expectedBIOS[biosString]:
                diffBIOS.append("%s = \"%s\", expected value: \"%s\"" %
                 (biosString, guestxsBIOS[biosString], expectedBIOS[biosString]))

        # Compare OEM Strings
        numGuestOEMStrings = len(guestxsBIOS[OEM_STRINGS])
        numExpectedOEMStrings = len(expectedBIOS[OEM_STRINGS])

        if numGuestOEMStrings != numExpectedOEMStrings:
            diffBIOS.append("Expected OEM Strings:\n%s" % 
                            "\n".join(map(lambda x,y:"%s%s = %s" %
                                                     (XENSTORE_OEM_PREFIX, x, y),
                                          range(1, numExpectedOEMStrings+1),
                                          expectedBIOS[OEM_STRINGS])))
            diffBIOS.append("Actual OEM Strings:\n%s" % 
                            "\n".join(map(lambda x,y:"%s%s = %s" %
                                                     (XENSTORE_OEM_PREFIX, x, y),
                                          range(1, numGuestOEMStrings+1), 
                                          guestxsBIOS[OEM_STRINGS])))
        else:
            for i in range(numExpectedOEMStrings):
                if guestxsBIOS[OEM_STRINGS][i] != expectedBIOS[OEM_STRINGS][i]:
                    diffBIOS.append("%s%s = \"%s\", expected value: \"%s\"" %
                                    (XENSTORE_OEM_PREFIX, 
                                     i+1, 
                                     guestxsBIOS[OEM_STRINGS][i],
                                     expectedBIOS[OEM_STRINGS][i]))

        if diffBIOS:
            raise xenrt.XRTFailure("Unexpected BIOS strings found in xenstore",
                                   "\n".join(diffBIOS))

    def checkGuestDMIBIOS(self, guestdmiBIOS, guestxsBIOS, dmiGenBIOS):
        diffBIOS = []
        # Compare all values except OEM Strings
        for biosString in XENSTORE_BIOS_STRINGS:
            # When the xenstore strings are empty, the product uses the generic
            # strings in the DMI tables. But for the serial number, a different
            # value is created for each VM.
            expectedValue = guestxsBIOS[biosString]
            if not expectedValue:
                if biosString == SYSTEM_SERIAL_NUMBER:
                    continue
                expectedValue = dmiGenBIOS[biosString]

            if guestdmiBIOS[biosString] != expectedValue:
                diffBIOS.append("%s = \"%s\", expected value: \"%s\"" %
                 (biosString, guestdmiBIOS[biosString], expectedValue))

        # Compare OEM Strings
        numGuestDMIOEMStrings = len(guestdmiBIOS[OEM_STRINGS])
        numGuestXSOEMStrings = len(guestxsBIOS[OEM_STRINGS])

        if numGuestDMIOEMStrings != numGuestXSOEMStrings:
            diffBIOS.append("Expected OEM Strings:\n%s" %
                            "\n".join(map(lambda x,y:"%s%s = %s" %
                                                     (DMI_OEM_PREFIX, x, y),
                                          range(1, numGuestXSOEMStrings+1),
                                          guestxsBIOS[OEM_STRINGS])))
            diffBIOS.append("Actual OEM Strings:\n%s" %
                            "\n".join(map(lambda x,y:"%s%s = %s" %
                                                     (DMI_OEM_PREFIX, x, y),
                                          range(1, numGuestDMIOEMStrings+1),
                                          guestdmiBIOS[OEM_STRINGS])))
        else:
            for i in range(numGuestXSOEMStrings):
                if guestdmiBIOS[OEM_STRINGS][i] != guestxsBIOS[OEM_STRINGS][i]:
                    diffBIOS.append("%s%s = \"%s\", expected value: \"%s\"" %
                                    (DMI_OEM_PREFIX,
                                     i+1,
                                     guestdmiBIOS[OEM_STRINGS][i],
                                     guestxsBIOS[OEM_STRINGS][i]))

        if diffBIOS:
            raise xenrt.XRTFailure("Unexpected BIOS strings found in dmidecode output",
                                   "\n".join(diffBIOS))

    def run(self, arglist=None):
        # Install a BIOS-customized VM
        pool = self.getDefaultPool()
        guest = pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                biosHostUUID=pool.master.getMyHostUUID(),
                                ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(guest)

        # Check the BIOS status of the VM is reported as customized
        cli = pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (guest.getName()),
                                      strip=True)

        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Get BIOS Strings for the Host, Guest, and DMI Generic BIOS
        guestxsBIOS = self.getXenStoreBIOS(guest.getDomid(), pool.master)
        guestdmiBIOS = self.getDMIBIOS(guest)
        hostdmiBIOS = self.getDMIBIOS(pool.master)
        dmiGenBIOS = self.getDMIGenericBIOS(pool.master.paramGet("software-version", "xen"))

        self.checkGuestXenStoreBIOS(guestxsBIOS, hostdmiBIOS)
        self.checkGuestDMIBIOS(guestdmiBIOS, guestxsBIOS, dmiGenBIOS)

        guest.check()

class TC10191(TC10190):
    """Install a BIOS-generic Linux HVM VM"""
    
    def run(self, arglist=None):
        pool = self.getDefaultPool()
        guest = pool.master.createRamdiskLinuxGuest(memory=self.MEMORY,
                                                ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(guest)

        # Check the BIOS status of the VM is reported as generic
        cli = pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (guest.getName()),
                                      strip=True)

        if guestBiosStatus != GENERIC_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-generic")

        # Get the Guest BIOS Strings and DMI Generic BIOS
        guestdmiBIOS = self.getDMIBIOS(guest)
        guestxsBIOS = self.getXenStoreBIOS(guest.getDomid(), pool.master)
        dmiGenBIOS = self.getDMIGenericBIOS(pool.master.paramGet("software-version", "xen"))

        self.checkGuestXenStoreBIOS(guestxsBIOS, XENSTORE_GENERIC_BIOS)
        self.checkGuestDMIBIOS(guestdmiBIOS, guestxsBIOS, dmiGenBIOS)

        guest.check()

class TC10192(TC10190):
    """Mark a VM without BIOS strings as BIOS-customized"""

    def run(self, arglist=None):
        pool = self.getDefaultPool()
        guest = pool.master.createRamdiskLinuxGuest(start=False, 
                                                    memory=self.MEMORY,
                                                 ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(guest)

        # Check the BIOS status of the VM is reported as not set
        cli = pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized", 
                                      "vm=%s" % (guest.getName()),
                                      strip=True)
        if guestBiosStatus != NO_BIOS_STATUS:
            raise xenrt.XRTFailure("BIOS strings of new VM are already set: %s" %
                                   (guestBiosStatus))

        # Mark the VM as BIOS-customized
        cli.execute("vm-copy-bios-strings", "vm=%s host-uuid=%s " %
                    (guest.getName(), pool.master.getMyHostUUID()))

        # Check the BIOS status of the VM is reported as customized
        guestBiosStatus = cli.execute("vm-is-bios-customized", 
                                      "vm=%s" % (guest.getName()),
                                      strip=True)

        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Check the VM starts and it's happy
        guest.start()
        if not guest.mainip:
            raise xenrt.XRTFailure("Could not find ramdisk guest IP address")
        guest.waitForSSH(600)

        # Get BIOS Strings for the Host, Guest, and DMI Generic BIOS
        guestxsBIOS = self.getXenStoreBIOS(guest.getDomid(), pool.master)
        guestdmiBIOS = self.getDMIBIOS(guest)
        hostdmiBIOS = self.getDMIBIOS(pool.master)
        dmiGenBIOS = self.getDMIGenericBIOS(pool.master.paramGet("software-version", "xen"))

        self.checkGuestXenStoreBIOS(guestxsBIOS, hostdmiBIOS)
        self.checkGuestDMIBIOS(guestdmiBIOS, guestxsBIOS, dmiGenBIOS)

        guest.check()

class TC10193(TC10190):
    """Verify operation to mark a BIOS-customized VM as BIOS-customized again is blocked"""

    def prepare(self, arglist):
        # Install a BIOS-customized VM
        self.pool = self.getDefaultPool()
        self.guest = self.pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                    biosHostUUID=self.pool.master.getMyHostUUID(),
                                    ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):
        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)

        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Mark the VM as BIOS-customized again by specifying a different host
        slave = self.pool.slaves[self.pool.slaves.keys()[0]]
        allowed = False
        try:
            cli.execute("vm-copy-bios-strings", "vm=%s host-uuid=%s " %
                        (self.guest.getName(), slave.getMyHostUUID()))
            allowed = True
        except:
            pass

        if allowed:
            raise xenrt.XRTFailure("Allowed to mark a BIOS-customized VM as "
                                   "BIOS-customized again when operation "
                                   "should be blocked")

        self.guest.reboot()

        # Check the BIOS status of the VM is still reported as customized
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)

        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        self.guest.check()

class TC10194(TC10190):
    """Verify operation to mark a BIOS-generic VM as BIOS-customized is blocked"""

    def run(self, arglist=None):
        # Install a BIOS-generic VM
        pool = self.getDefaultPool()
        guest = pool.master.createRamdiskLinuxGuest(memory=self.MEMORY,
                                                ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(guest)

        # Check the BIOS status of the VM is reported as generic
        cli = pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (guest.getName()),
                                      strip=True)

        if guestBiosStatus != GENERIC_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-generic")

        guest.shutdown()

        # Mark the VM as BIOS-customized
        allowed = False
        try:
            cli.execute("vm-copy-bios-strings", "vm=%s host-uuid=%s " %
                        (guest.getName(), pool.master.getMyHostUUID()))
            allowed = True
        except:
            pass

        if allowed:
            raise xenrt.XRTFailure("Allowed to mark a BIOS-generic VM as "
                                   "BIOS-customized when operation "
                                   "should be blocked")

        guest.start()

        # Check the BIOS status of the VM is still reported as generic
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (guest.getName()),
                                      strip=True)

        if guestBiosStatus != GENERIC_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-generic")

        guest.check()

class TC10195(TC10193):
    """Verify the custom SMBIOS strings are not exposed by the CLI"""

    def run(self, arglist=None):
        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)

        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Get the VM's SMBIOS Strings
        guestxsBIOS = self.getXenStoreBIOS(self.guest.getDomid(), self.pool.master)

        # Check the SMBIOS strings are not exposed by the CLI
        vmData = cli.execute("vm-param-list", 
                             "uuid=%s" % (self.guest.getUUID()),
                             strip=True)
        cliBIOS = []
        
        xenrt.TEC().logverbose(vmData)

        for line in vmData.splitlines():
            # Look for BIOS strings, except OEM strings, in the CLI output
            found = False
            for biosString in XENSTORE_BIOS_STRINGS:
                if guestxsBIOS[biosString] and \
                   guestxsBIOS[biosString] != "." and \
                   guestxsBIOS[biosString] in line:
                    cliBIOS.append(line)
                    found = True
                    break
            if found:
                continue

            # Look for OEM strings in the CLI output
            for i in range(len(guestxsBIOS[OEM_STRINGS])):
                if guestxsBIOS[OEM_STRINGS][i] and \
                   guestxsBIOS[OEM_STRINGS][i] != "." and \
                   guestxsBIOS[OEM_STRINGS][i] in line:
                    cliBIOS.append(line)
                    break

        if cliBIOS:
            xenrt.TEC().logverbose("Custom SMBIOS strings are exposed by "
                                   "the CLI:\n%s" % "\n".join(cliBIOS))
            raise xenrt.XRTFailure("Custom SMBIOS strings are exposed by the CLI")

class TC10196(TC10190):
    """Install a BIOS-customized Linux HVM VM, by copying the BIOS strings from a pool slave"""

    def run(self, arglist=None):
        # Install a BIOS-customized VM
        pool = self.getDefaultPool()
        slave = pool.slaves[pool.slaves.keys()[0]]
        guest = pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                biosHostUUID=slave.getMyHostUUID(),
                                ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(guest)

        # Check the BIOS status of the VM is reported as customized
        cli = pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (guest.getName()),
                                      strip=True)

        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Get BIOS Strings for the Host, Guest, and DMI Generic BIOS
        guestxsBIOS = self.getXenStoreBIOS(guest.getDomid(), pool.master)
        guestdmiBIOS = self.getDMIBIOS(guest)
        hostdmiBIOS = self.getDMIBIOS(slave)
        dmiGenBIOS = self.getDMIGenericBIOS(pool.master.paramGet("software-version", "xen"))

        self.checkGuestXenStoreBIOS(guestxsBIOS, hostdmiBIOS)
        self.checkGuestDMIBIOS(guestdmiBIOS, guestxsBIOS, dmiGenBIOS)

        guest.check()

class TC10197(TC10190):
    """Verify operation to install a BIOS-customized VM by copying the BIOS strings from an invalid host is blocked"""

    def run(self, arglist=None):
        pool = self.getDefaultPool()
        allowed = False
        try:
            guest = pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                           biosHostUUID="00000000-0000-0000-0000-000000000000")
            allowed = True
            self.uninstallOnCleanup(guest)
        except:
            pass

        if allowed:
            raise xenrt.XRTFailure("Allowed to install a BIOS-customized VM by "
                                   "specifying an invalid host UUID to copy "
                                   "BIOS strings from")

class TC10198(TC10190):
    """Install a VM from a BIOS-customized template"""

    def createPXEFileForMac(self, mac):
        pxe = xenrt.PXEBoot(abspath=True,removeOnExit=True)
        pxecfg = pxe.addEntry("cleanrd", default=1, boot="linux")
        barch = self.pool.master.getBasicArch()
        pxecfg.linuxSetKernel("clean/vmlinuz-xenrt-%s" % (barch))
        pxecfg.linuxArgsKernelAdd("root=/dev/ram0")
        pxecfg.linuxArgsKernelAdd("console=tty0")
        pxecfg.linuxArgsKernelAdd("maxcpus=1")
        pxecfg.linuxArgsKernelAdd("console=ttyS0,115200n8")
        pxecfg.linuxArgsKernelAdd("ramdisk_size=%d" % (self.RAMDISK_SIZE))
        pxecfg.linuxArgsKernelAdd("ro")
        pxecfg.linuxArgsKernelAdd("initrd=clean/cleanroot-%s.img.gz" % (barch))
        pxefile = pxe.writeOut(None,forcemac=mac)

    def run(self, arglist=None):
        # Install a BIOS-customized VM
        self.pool = self.getDefaultPool()
        self.guest = self.pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                    biosHostUUID=self.pool.master.getMyHostUUID(),
                                    ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(self.guest)

        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Get the SMBIOS Strings of the VM that will be used as a template
        templatexsBIOS = self.getXenStoreBIOS(self.guest.getDomid(), self.pool.master)

        self.guest.shutdown()
        self.guest.removeVIF("eth0")
        self.guest.paramSet("is-a-template", "true")
        template = self.guest

        # Install a new VM from the BIOS-customized template
        vm = self.pool.master.guestFactory()(xenrt.randomGuestName(),
                                     template=template.getName(),
                                     host=self.pool.master)
        vm.createGuestFromTemplate(vm.template, sruuid=None)
        self.uninstallOnCleanup(vm)

        mac = xenrt.randomMAC()
        vm.createVIF(bridge=self.pool.master.getPrimaryBridge(), mac=mac)
        vm.enlightenedDrivers = False

        # Create PXE file for the new VM so that it can boot
        self.createPXEFileForMac(mac)
        vm.start()
        if not vm.mainip:
            raise xenrt.XRTError("Could not find ramdisk guest IP address")
        vm.waitForSSH(600)

        # Check the BIOS status of the new VM is reported as customized
        vmBiosStatus = cli.execute("vm-is-bios-customized",
                                   "vm=%s" % (vm.getName()),
                                   strip=True)

        if vmBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM created from a BIOS-customized "
                                   "template is not BIOS-customized")

        # Get the new VM's SMBIOS Strings and check them against the template's
        vmxsBIOS = self.getXenStoreBIOS(vm.getDomid(), self.pool.master)
        vmdmiBIOS = self.getDMIBIOS(vm)
        dmiGenBIOS = self.getDMIGenericBIOS(self.pool.master.paramGet("software-version", "xen"))

        self.checkGuestXenStoreBIOS(vmxsBIOS, templatexsBIOS)
        self.checkGuestDMIBIOS(vmdmiBIOS, templatexsBIOS, dmiGenBIOS)

        # Allow the template to get uninstalled on cleanup
        template.paramSet("is-a-template", "false")

        # Check the affinity field is set to the master host
        if vm.paramGet("affinity") != self.pool.master.getMyHostUUID():
            raise xenrt.XRTFailure("The VM created from a BIOS-customized " 
                                   "template does not have the affinity set "
                                   "to the pool master")

class TC10199(TC10190):
    """Concurrent execution of BIOS-customized and BIOS-generic VMs"""

    NUM_CUSTOM_VMS = 2
    NUM_GENERIC_VMS = 2
    GENERIC_MEM = 512
    ITERATIONS = 1

    def run(self, arglist=None):
        pool = self.getDefaultPool()
        cli = pool.getCLIInstance()
        guests = []

        # Install BIOS-customized guests
        for i in range(self.NUM_CUSTOM_VMS):
            guest = pool.master.installHVMLinux(memory=self.MEMORY,
                                    biosHostUUID=pool.master.getMyHostUUID(),
                                    ramdisk_size=self.RAMDISK_SIZE,start=True)
            self.uninstallOnCleanup(guest)
            guests.append(guest)

            guestBiosStatus = cli.execute("vm-is-bios-customized",
                                          "vm=%s" % (guest.getName()),
                                          strip=True)
            if guestBiosStatus != CUSTOM_BIOS_STATUS:
                raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Install BIOS-generic VMs
        for i in range(self.NUM_GENERIC_VMS):
            guest = pool.master.createGenericLinuxGuest(memory=self.GENERIC_MEM)
            self.uninstallOnCleanup(guest)
            guests.append(guest)

            guestBiosStatus = cli.execute("vm-is-bios-customized",
                                          "vm=%s" % (guest.getName()),
                                          strip=True)
            if guestBiosStatus != GENERIC_BIOS_STATUS:
                raise xenrt.XRTFailure("The VM is not BIOS-generic")

        success = 0
        abort = False
        try:
            for i in range(self.ITERATIONS):
                xenrt.TEC().logdelimit("loop iteration %u..." % (i))
                for j in range(len(guests)):
                    if j < self.NUM_CUSTOM_VMS:
                        guests[j].pretendToHaveXenTools()
                        time.sleep(5)
                    guests[j].suspend()
                    guests[j].resume()
                    guests[j].reboot()
                    guests[j].check()
                    if xenrt.GEC().abort:
                        xenrt.TEC().warning("Aborting on command")
                        abort = True
                        break
                if abort:
                    break
                success += 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success, self.ITERATIONS))

class TC10200(TC10190):
    """Verify BIOS customization is preserved across migration"""

    def run(self, arglist=None):
        # Install a BIOS-customized VM
        self.pool = self.getDefaultPool()
        self.guest = self.pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                    biosHostUUID=self.pool.master.getMyHostUUID(),
                                    ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(self.guest)

        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Get the SMBIOS Strings of the VM prior to migration
        vmxsBIOS_1 = self.getXenStoreBIOS(self.guest.getDomid(), self.pool.master)
        vmdmiBIOS_1 = self.getDMIBIOS(self.guest)
        dmiGenBIOS = self.getDMIGenericBIOS(self.pool.master.paramGet("software-version", "xen"))

        # Live migrate the VM
        current = self.pool.master
        dest = self.pool.slaves[self.pool.slaves.keys()[0]]

        xenrt.TEC().logverbose("Live migrating from %s to %s" %
                               (current.getName(), dest.getName()))
        self.guest.pretendToHaveXenTools()
        self.guest.migrateVM(dest, live="true")
        self.guest.check()

        # Check the BIOS status of the VM is still reported as customized
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Get the SMBIOS Strings of the VM post migration
        vmxsBIOS_2 = self.getXenStoreBIOS(self.guest.getDomid(), dest)
        vmdmiBIOS_2 = self.getDMIBIOS(self.guest)

        self.checkGuestXenStoreBIOS(vmxsBIOS_2, vmxsBIOS_1)
        self.checkGuestDMIBIOS(vmdmiBIOS_2, vmdmiBIOS_1, dmiGenBIOS)

class TC10201(TC10190):
    """Verify BIOS customization is preserved across export/import"""

    def run(self, arglist=None):
        # Install a BIOS-customized VM
        self.pool = self.getDefaultPool()
        self.guest = self.pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                    biosHostUUID=self.pool.master.getMyHostUUID(),
                                    ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(self.guest)

        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Check it's happy
        self.guest.check()

        # Get the SMBIOS Strings of the VM prior to export
        vmxsBIOS_1 = self.getXenStoreBIOS(self.guest.getDomid(), self.pool.master)
        vmdmiBIOS_1 = self.getDMIBIOS(self.guest)

        self.guest.shutdown()

        # Export, uninstall, and import the VM
        slave = self.pool.slaves[self.pool.slaves.keys()[0]]
        tf = xenrt.TEC().tempFile()
        try:
            self.guest.exportVM(tf)
            self.guest.uninstall()
            self.guest.vifs = []
            self.guest.importVM(slave, tf, preserve=True, ispxeboot=True)

            # Reset flags to False before starting the VM. The importVM sets 
            # them to True when it calls the "existing" method.
            self.guest.enlightenedDrivers = False
            self.guest.start()
        finally:
            if os.path.exists(tf):
                os.unlink(tf)

        # Check the BIOS status of the imported VM is reported as customized
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The imported VM is not BIOS-customized")

        # Get the SMBIOS Strings of the imported VM
        vmxsBIOS_2 = self.getXenStoreBIOS(self.guest.getDomid(), slave)
        vmdmiBIOS_2 = self.getDMIBIOS(self.guest)
        dmiGenBIOS = self.getDMIGenericBIOS(slave.paramGet("software-version", "xen"))

        self.checkGuestXenStoreBIOS(vmxsBIOS_2, vmxsBIOS_1)
        self.checkGuestDMIBIOS(vmdmiBIOS_2, vmdmiBIOS_1, dmiGenBIOS)

        # Check it's happy
        self.guest.check()

class TC10202(TC10193):
    """Live migrate loop of a BIOS-customized VM"""

    ITERATIONS = 50 

    def run(self, arglist=None):
        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Check it's happy
        self.guest.check()

        # Do a live migrate loop
        success = 0
        current = self.pool.master
        dest = self.pool.slaves[self.pool.slaves.keys()[0]]
        try:
            for i in range(self.ITERATIONS):
                xenrt.TEC().logverbose("Live migrating from %s to %s" %
                                       (current.getName(), dest.getName()))
                self.guest.pretendToHaveXenTools()
                self.guest.migrateVM(dest,live="true")
                self.guest.check()
                temp = current
                current = dest
                dest = temp
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success, self.ITERATIONS))

class TC10203(TC10193):
    """Suspend/resume loop of a BIOS-customized VM"""

    ITERATIONS = 50

    def run(self, arglist=None):
        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Check it's happy
        self.guest.check()

        # Do a suspend resume loop
        success = 0
        try:
            for i in range(self.ITERATIONS):
                self.guest.pretendToHaveXenTools()
                time.sleep(5)
                self.guest.suspend()
                self.guest.resume()
                self.guest.check()
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success, self.ITERATIONS))

class TC10204(TC10193):
    """Shutdown/start/reboot loop of a BIOS-customized VM"""

    ITERATIONS = 10

    def run(self, arglist=None):
        # Check the BIOS status of the VM is reported as customized
        cli = self.pool.getCLIInstance()
        guestBiosStatus = cli.execute("vm-is-bios-customized",
                                      "vm=%s" % (self.guest.getName()),
                                      strip=True)
        if guestBiosStatus != CUSTOM_BIOS_STATUS:
            raise xenrt.XRTFailure("The VM is not BIOS-customized")

        # Check it's happy
        self.guest.check()

        # Do a shutdown/start/reboot loop
        success = 0
        try:
            for i in range(self.ITERATIONS):
                self.guest.shutdown()
                self.guest.start()
                self.guest.check()
                self.guest.reboot()
                self.guest.check()
                success += 1
                if xenrt.GEC().abort:
                    xenrt.TEC().warning("Aborting on command")
                    break
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success, self.ITERATIONS))
class TC10534(TC10200):
    """Verify BIOS customization is preserved across migration to a host with different BIOS Strings"""

class TC10535(TC10201):
    """Verify BIOS customization is preserved across export/import into a host with different BIOS Strings"""

class TC11162(xenrt.TestCase):
    """Verify a BIOS-customized HVM VM starts on Master host from which BIOS Strings were copied"""

    MEMORY = 768
    RAMDISK_SIZE = 550000

    def run(self, arglist=None):
        # Install a BIOS-customized VM
        pool = self.getDefaultPool()
        poolMasterUUID = pool.master.getMyHostUUID()
        guest = pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                biosHostUUID=poolMasterUUID,
                                ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(guest)

        guest.shutdown()
        guest.start(specifyOn=False, skipsniff=True)

        # Check the affinity field is set to the master host
        if guest.paramGet("affinity") != poolMasterUUID:
            raise xenrt.XRTFailure("The VM's affinity is not set to the pool "
                                   "master from which BIOS Strings were copied")

        # Check the VM is running on the master host
        if guest.paramGet("resident-on") != poolMasterUUID:
            raise xenrt.XRTFailure("The VM was not started on the pool master "
                                   "from which BIOS Strings were copied")

class TC11163(xenrt.TestCase):
    """Verify a BIOS-customized HVM VM starts on Slave host from which BIOS Strings were copied"""

    MEMORY = 768
    RAMDISK_SIZE = 550000

    def run(self, arglist=None):
        # Install a BIOS-customized VM
        pool = self.getDefaultPool()
        slaveUUID = pool.slaves[pool.slaves.keys()[0]].getMyHostUUID()
        guest = pool.master.installRamdiskLinuxGuest(memory=self.MEMORY,
                                biosHostUUID=slaveUUID,
                                ramdisk_size=self.RAMDISK_SIZE)
        self.uninstallOnCleanup(guest)

        guest.shutdown()
        guest.start(specifyOn=False, skipsniff=True)

        # check the affinity field is set to the slave host
        if guest.paramGet("affinity") != slaveUUID:
            raise xenrt.XRTFailure("The VM's affinity is not set to the pool "
                                   "slave from which BIOS Strings were copied")

        # Check the VM is running on the slave host
        if guest.paramGet("resident-on") != slaveUUID:
            raise xenrt.XRTFailure("The VM was not started on the pool slave "
                                   "from which BIOS Strings were copied")

