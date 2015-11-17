#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a XenServer host installer process.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, os.path, glob, re, stat, os, traceback
import xenrt
import xenrt.lib.xenserver

class DundeeInstaller(object):
    def __init__(self, host):
        self.host = host

    def install(self,
                cd=None,
                primarydisk=None,
                guestdisks=["sda"],
                source="url",
                timezone="UTC",
                interfaces=[(None, "yes", "dhcp", None, None, None, None, None, None)],
                ntpserver=None,
                nameserver=None,
                hostname=None,
                extracds=None,
                upgrade=False,
                async=False,
                installSRType=None,
                overlay=None,
                suppackcds=None,
                installnetwork=None):
        
        xenrt.TEC().logverbose("DundeeInstaller.install")

        uefi = self.host.lookup("UEFI_BOOT", False, boolean=True)

        self.extrapi = ""
        self.upgrade = upgrade
        self.overlay = overlay

        if not self.upgrade:
            # Default for primary disk only if not an upgrade
            if not primarydisk:
                primarydisk = "sda"

            # Store the arguments for the reinstall and check commands
            self.host.i_cd = cd
            self.host.i_primarydisk = primarydisk
            self.host.i_guestdisks = guestdisks
            self.host.i_source = source
            self.host.i_timezone = timezone
            self.host.i_interfaces = interfaces
            self.host.i_ntpserver = ntpserver
            self.host.i_nameserver = nameserver
            self.host.i_hostname = hostname
            self.host.i_extracds = extracds
            self.host.i_upgrade = self.upgrade
            self.host.i_async = async
            self.host.i_suppackcds = suppackcds

        if self.upgrade:
            # Default to existing values if not specified
            if not primarydisk:
                if self.host.i_primarydisk:
                    primarydisk = self.host.i_primarydisk
                    # Handle the case where its a cciss disk going into a Dundee+ host with CentOS 6.4+ udev rules
                    # In this situation a path that includes cciss- will not work. See CA-121184 for details
                    if "cciss" in primarydisk:
                        primarydisk = self.host.getInstallDisk(ccissIfAvailable=self.host.USE_CCISS, legacySATA=False)
                else:
                    primarydisk = "sda"

            # Try to capture a bugtool before the upgrade
            try:
                xenrt.TEC().logverbose("Capturing bugtool before upgrade of %s"
                                       % (self.host.getName()))
                self.host.getBugTool()
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception getting bugtool before upgrade:"
                                    " %s" % (str(e)))

        self.host.cd = cd
        self.getCD()
        
        self.host.password = self.host.lookup("ROOT_PASSWORD")

        self.host.installnetwork = installnetwork
        if installnetwork:
            nicid = self.host.listSecondaryNICs(installnetwork)[0]
            net = self.host.getNICAllocatedIPAddress(nicid)
            self.host.setIP(net[0])
        
        workdir = xenrt.TEC().getWorkdir()
        
        xenrt.TEC().progress("Starting installation of XenServer host on %s" %
                             (self.host.machine.name))
        
        # Pull installer boot files from CD image and put into PXE
        # directory
        xenrt.TEC().logverbose("Using ISO %s" % (self.host.cd))
        mount = xenrt.MountISO(self.host.cd)
        mountpoint = mount.getMount()
        
        # Copy installer packages to a web/nfs directory
        if source == "url":
            self.packdir = xenrt.WebDirectory()
            self.pidir = xenrt.WebDirectory()
        elif source == "nfs":
            self.packdir = xenrt.NFSDirectory()
            self.pidir = xenrt.NFSDirectory()
        else:
            raise xenrt.XRTError("Unknown install source method '%s'." %
                                 (source))
        # Copy ISO layout
        self.packdir.copyIn("%s/*" % (mountpoint))

        self.setupExtraInstallPackages(extracds, suppackcds)

        # Create an NFS directory for the installer to signal completion
        self.signaldir = xenrt.NFSDirectory()
        
        ansfile = self.createInstallAnswerfile(primarydisk,
                                               guestdisks,
                                               interfaces,
                                               source,
                                               nameserver,
                                               ntpserver,
                                               hostname,
                                               installSRType,
                                               timezone,
                                               installnetwork)
        
        self.createPostInstallFiles(uefi=uefi)
        answerfileUrl = self.packdir.getURL(ansfile)
        
        if uefi:
            pxe = xenrt.PXEBootUefi()
            self.setupInstallUefiPxe(pxe, mountpoint, answerfileUrl)
        else:
            # Get a PXE directory to put boot files in
            pxe = xenrt.PXEBoot(iSCSILUN = self.host.bootLun, ipxeInUse = self.host.lookup("USE_IPXE", False, boolean=True))
            self.setupInstallPxe(pxe, mountpoint, answerfileUrl)
        # We're done with the ISO now
        mount.unmount()
        
        # Reboot the host into the installer
        if self.host.lookup("INSTALL_DISABLE_FC", False, boolean=True):
            self.host.disableAllFCPorts()
        if self.upgrade:
            self.host._softReboot()
        else:
            self.host.machine.powerctl.cycle()
            
        xenrt.TEC().progress("Rebooted host to start installation.")
        if async:
            handle = (self.signaldir, None, pxe, uefi)
            return handle
        handle = (self.signaldir, self.packdir, pxe, uefi)
        if xenrt.TEC().lookup("OPTION_BASH_SHELL", False, boolean=True):
            xenrt.TEC().tc.pause("Pausing due to bash-shell option")
            
        
        
        # this option allows manual installation i.e. you step through
        # the XS installer manually and it detects for when this is finished.
        if xenrt.TEC().lookup("OPTION_NO_ANSWERFILE", False, boolean=True):
            
            xenrt.TEC().logverbose("User is to step through installer manually")
            xenrt.TEC().logverbose("Waiting 5 mins")
            
            # wait 5 mins
            xenrt.sleep(5 * 60)
           
            # now fix-up the pxe file for local boot
            xenrt.TEC().logverbose("Setting PXE file to be local boot by default")
            if uefi and not self.host.lookup("PXE_CHAIN_UEFI_BOOT", False, boolean=True):
                pxe.uninstallBootloader(self.host.machine)
            else:
                pxe.setDefault("local")
                pxe.writeOut(self.host.machine)
            if self.host.bootLun:
                pxe.writeISCSIConfig(self.host.machine, boot=True)
            
            # now wait for SSH to come up. Allow an hour for the installer
            # to be completed manually
            self.host.waitForSSH(3600, desc="Host boot (!%s)" % (self.host.getName()))

            self.host.installComplete(handle, waitfor=False, upgrade=self.upgrade)
        else:
            self.host.installComplete(handle, waitfor=True, upgrade=self.upgrade)

        return None

    @property
    def forceUefiBootViaPxe(self):
        if self.host.lookup("PXE_CHAIN_UEFI_BOOT", False, boolean=True):
            # We need to do this otherwise the local disk will boot first and XenServer will never boot
            return "efibootmgr -B -b `efibootmgr -v | grep XenServer | awk '{print $1}' | sed 's/Boot//'`"
        else:
            return ""

    @property
    def postInstallBootMods(self):
        def setXen(data):
            return "/opt/xensource/libexec/xen-cmdline --set-xen '%s'" % data
        def setDom0(data):
            return "/opt/xensource/libexec/xen-cmdline --set-dom0 '%s'" % data
        def deleteXen(data):
            return "/opt/xensource/libexec/xen-cmdline --delete-xen '%s'" % data

        dom0_extra_args = self.host.lookup("DOM0_EXTRA_ARGS", None)
        dom0_extra_args_user = self.host.lookup("DOM0_EXTRA_ARGS_USER", None)
        xen_extra_args = self.host.lookup("XEN_EXTRA_ARGS", None)
        xen_extra_args_user = self.host.lookup("XEN_EXTRA_ARGS_USER", None)
        if xen_extra_args_user:
            xen_extra_args_user = string.replace(xen_extra_args_user, ",", " ")
        dom0mem = xenrt.TEC().lookup("OPTION_DOM0_MEM", None)
        dom0blkbkorder = xenrt.TEC().lookup("DOM0_BLKBKORDER", None)
        dom0rdsize = xenrt.TEC().lookup("DOM0_RDSIZE", None)

        cmds = []
        if dom0mem:
            cmds.append(setXen("dom0_mem=%sM,max:%sM" % (dom0mem, dom0mem)))
        if xenrt.TEC().lookup("OPTION_DEBUG", False, boolean=True):
            cmds.append(setDom0("print-fatal-signals=2"))
            cmds.append(setXen("loglvl=all guest_loglvl=all"))
        if dom0_extra_args:
            cmds.append(setDom0(dom0_extra_args))
        if dom0_extra_args_user:
            cmds.append(setDom0(dom0_extra_args_user))
        if xen_extra_args:
            cmds.append(setXen(xen_extra_args))
        if xen_extra_args_user:
            cmds.append(setXen(xen_extra_args_user))
        if self.host.lookup("XEN_DISABLE_WATCHDOG", False, boolean=True):
            cmds.append(deleteXen("watchdog"))
            cmds.append(deleteXen("watchdog_timeout"))
            cmds.append(setDom0("watchdog=false"))
        if (dom0blkbkorder):
            cmds.append(setDom0("blkbk.max_ring_page_order=%s" % dom0blkbkorder))
        if dom0rdsize:
            cmds.append(setDom0("ramdisk_size=%s" % dom0rdsize))

        return """
# Fix up the bootloader configuration.
cp boot/extlinux.conf boot/extlinux.conf.orig || true
cp boot/grub/grub.cfg boot/grub/grub.cfg.orig || true
cp boot/efi/EFI/xenserver/grub.cfg boot/efi/EFI/xenserver/grub.cfg.orig || true

# Run the bootloader commands in a chroot
cat > bootloader << EOF
#!/bin/sh

%s
EOF
chmod +x bootloader

chroot . /bootloader

rm -f bootloader

""" % ("\n".join(cmds))

    @property
    def postInstallSSHKey(self):
        ssh_key = xenrt.getPublicKey()
        return """
mkdir -p root/.ssh
chmod 700 root/.ssh
echo '%s' > root/.ssh/authorized_keys
chmod 600 root/.ssh/authorized_keys
""" % ssh_key

    @property
    def postInstallCoreDump(self):
        return """
# Allow the agent to dump core
mv etc/init.d/xapi etc/init.d/xapi.orig
awk '{print;if(FNR==1){print "DAEMON_COREFILE_LIMIT=unlimited"}}' < etc/init.d/xapi.orig > etc/init.d/xapi
chmod 755 etc/init.d/xapi
"""

    @property
    def postInstallXapiTweak(self):
        xapiargs = xenrt.TEC().lookup("XAPI_EXTRA_ARGS", None)
        if xapiargs:
            xenrt.TEC().warning("Using extra args to xapi: %s" % (xapiargs))
            xapitweak = """# Add extra command line args to xapi
mv etc/init.d/xapi etc/init.d/xapi.origtweak
sed -e's#/opt/xensource/bin/xapi#/opt/xensource/bin/xapi %s#' < etc/init.d/xapi.origtweak > etc/init.d/xapi
chmod 755 etc/init.d/xapi
""" % (xapiargs)
        else:
            xapitweak = ""
            
        return xapitweak

    @property
    def postInstallRedoLog(self):
        xapi_log_tweak = ""
        if xenrt.TEC().lookup('DEBUG_CA65062', False, boolean=True):
            xenrt.TEC().warning("Turning xapi redo_log logging ON")
            xapi_log_tweak = """#Turn xapi redo_log logging ON
mv etc/xensource/log.conf etc/xensource/log.conf.orig
sed -e 's/debug;redo_log;nil/#debug;redo_log;nil/' < etc/xensource/log.conf.orig > etc/xensource/log.conf
"""
        return xapi_log_tweak

    @property
    def postInstallUnplugDom0vCPUs(self):
        dom0cpus = xenrt.TEC().lookup("OPTION_XE_SMP_DOM0", None)
        if dom0cpus:
            xenrt.TEC().logverbose("Using %s CPUs in Domain-0." % (dom0cpus))
            unplugcpus = """
cp etc/init.d/unplug-vcpus root/unplug-vcpus.bak
CPUS=0
for i in /sys/devices/system/cpu/cpu*; do
    CPUS=$[ $CPUS + 1 ]
done

if [ "%s" == "ALL" ]; then
    DISABLEFROM=${CPUS} 
else
    DISABLEFROM=%s
fi

cat root/unplug-vcpus.bak | \
    sed -e "s/\/sys\/devices\/system\/cpu\/cpu\*/\`seq ${DISABLEFROM} $[ ${CPUS} - 1 ]\`/" \
        -e "s/\$i/\/sys\/devices\/system\/cpu\/cpu\$i/g" > etc/init.d/unplug-vcpus
""" % (dom0cpus, dom0cpus)
        else:
            unplugcpus = ""
        return unplugcpus 

    @property
    def postInstallBlacklistDrivers(self):
        blacklist = self.host.lookup("BLACKLIST_DRIVERS", None)
        if blacklist:
            blacklistdrivers = "echo -e \"%s\" > etc/modprobe.d/xrtblacklist.conf" % string.join(["blacklist %s" % x for x in blacklist.split(",")],"\\n")
        else:
            blacklistdrivers = ""
        return blacklistdrivers

    @property
    def postInstallSSH(self):
        if xenrt.TEC().lookup("TEST_INSTALLER_SSHPW", None) is not None:
            installer_ssh = "if [ -f /ssh_succeeded.txt ]; then cp /ssh_succeeded.txt .; fi"
        else:
            installer_ssh = ""
        return installer_ssh

    @property
    def postInstallDom0RamDisk(self):
        # Hack for a different ramdisk size
        dom0rdsizehack = ""
        dom0rdsize = xenrt.TEC().lookup("DOM0_RDSIZE", None)
        if dom0rdsize:
            dom0rdsizehack = """
# Set the dom0 ramdisk size
awk -F'---' {'if (NF==3) {print $1 "---" $2 "ramdisk_size=%s ---" $3} else print $0'} boot/extlinux.conf > /tmp/rdsizeboot.tmp
mv /tmp/rdsizeboot.tmp boot/extlinux.conf
""" % (dom0rdsize)
        return dom0rdsizehack

    @property
    def postInstallDom0MemPool(self):
        # Hack sm to assign mempools per vdi and not sr
        dom0mempoolhack = ""
        dom0mempool = xenrt.TEC().lookup("DOM0_MEMPOOL", None)
        if dom0mempool:
            dom0mempoolhack = """
cat << _EOF_ >> /tmp/mempool.patch
--- a/blktap2.py        2012-04-25 17:48:20.000000000 +0100
+++ b/blktap2.py        2012-04-25 17:48:57.000000000 +0100
@@ -35,7 +35,13 @@
 PLUGIN_TAP_PAUSE = "tapdisk-pause"
 
 NUM_PAGES_PER_RING = 32 * 11
-MAX_FULL_RINGS = 8
+
+def getmaxringpages():
+    order = int(open("/sys/module/blkbk/parameters/max_ring_page_order", "r").readline())
+    maxringpages = 1 << order
+    return maxringpages
+
+MAX_FULL_RINGS = getmaxringpages()
 
 ENABLE_MULTIPLE_ATTACH = "/etc/xensource/allow_multiple_vdi_attach"
 NO_MULTIPLE_ATTACH = not (os.path.exists(ENABLE_MULTIPLE_ATTACH)) 
@@ -1414,7 +1420,7 @@
 
         dev_path = self.setup_cache(sr_uuid, vdi_uuid, caching_params)
         if not dev_path:
-            self._set_blkback_pool(sr_uuid)
+            self._set_blkback_pool(vdi_uuid)
             phy_path = self.PhyLink.from_uuid(sr_uuid, vdi_uuid).readlink()
             # Maybe launch a tapdisk on the physical link
             if self.tap_wanted():
_EOF_
cd /opt/xensource/sm
patch -p1 < /tmp/mempool.patch
cd -
"""
        return dom0mempoolhack

    @property
    def postInstallNonDebugXen(self):
        # Since CP-5922, both a debug-enabled and a debug-disabled build of Xen are installed.
        # Optionally choose to employ the debug-disabled build by swizzling symlinks in /boot.
        usenondebugxen = ""
        if xenrt.TEC().lookup("FORCE_NON_DEBUG_XEN", None):
            usenondebugxen = self.host.swizzleSymlinksToUseNonDebugXen(pathprefix="")
        
        return usenondebugxen

    @property
    def postInstallFirstBootSR(self):
        firstBootSRSetup = ""
        if self.firstBootSRInfo:
            (disk, srtype) = self.firstBootSRInfo
            firstBootSRSetup = """
rm -f /etc/udev/rules.d/61-xenrt.rules
rm -f /dev/disk/by-id/*
if [ -e /sbin/udevadm ]
then
    sleep 5
    /sbin/udevadm trigger --action=add
    /sbin/udevadm settle
    sleep 5
    export XRTDISKLINKS=$(/sbin/udevadm info -q symlink -n %s)
else
    export XRTDISKLINKS=$(udevinfo -q symlink -n %s)
fi
echo $XRTDISKLINKS
export XRTDISK=$(echo -n $XRTDISKLINKS | awk '{ for (i=1; i<=NF; i++) { if (index($i, "disk/by-id") == 1 && index($i, "disk/by-id/edd") == 0 && index($i, "disk/by-id/wwn") == 0)  print $i;}}')
echo $XRTDISK

echo XSPARTITIONS=\\'/dev/$XRTDISK\\' >> etc/firstboot.d/data/default-storage.conf
echo XSTYPE='%s' >> etc/firstboot.d/data/default-storage.conf
echo PARTITIONS=\\'/dev/$XRTDISK\\' >> etc/firstboot.d/data/default-storage.conf
echo TYPE='%s' >> etc/firstboot.d/data/default-storage.conf
""" % (disk, disk, srtype, srtype)
        return firstBootSRSetup
        
    @property
    def postInstallOverlay(self):
        if self.overlay:
            overlaynfsurl = self.overlay.getMountURL("")
            ret = """
# Apply the overlay
mkdir /tmp/xenrtoverlaymount
mount -t nfs %s /tmp/xenrtoverlaymount
tar -cvf - -C /tmp/xenrtoverlaymount . | tar -xvf - -C $1
umount /tmp/xenrtoverlaymount
""" % overlaynfsurl
        else:
            ret = ""
        
        return ret

    @property
    def postInstallUsbWipe(self):
        usb = self.host.lookup("USB_BOOT_DEVICE", None)
        if usb:
            ret = """
# If we know we have a USB stick in this box dd zeros on to it to make sure
# it doesn't boot
if [ -n "%s" ]; then
    dd if=/dev/zero of=/dev/%s count=1024
fi""" % (usb, usb)
        else:
            ret = ""

        return ret

    @property
    def postInstallWriteCookie(self):
        return """
# Write a XenRT Insallation cookie
echo '%s' > root/xenrt-installation-cookie 
""" % self.host.installationCookie

    @property
    def postInstallStopSSH(self):
        return "service sshd stop || true\n"

    @property
    def postInstallSendBootLabel(self):
        # Use blkid to find the BOOT partition, and send the label back to the controller so we can put it in the grub config
        return """
# Write the boot label
mkdir -p /tmp/xenrttmpmount
mount -t nfs %s /tmp/xenrttmpmount
echo `blkid | grep BOOT | sed -n 's/.*LABEL=\\"\\([^\\"]*\\)\\".*/\\1/p'` > /tmp/xenrttmpmount/bootlabel
umount /tmp/xenrttmpmount
""" % self.signaldir.getMountURL("")
    
    @property
    def postInstallSignal(self):
        return """
# Signal XenRT that we've finished
mkdir -p /tmp/xenrttmpmount
mount -t nfs %s /tmp/xenrttmpmount
touch /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount
sleep 30
""" % self.signaldir.getMountURL("")
        

    def getCD(self):
        # Check and lookup variables and files
        if not self.host.cd:
            imageName = xenrt.TEC().lookup("CARBON_CD_IMAGE_NAME", 'main.iso')
            xenrt.TEC().logverbose("Using XS install image name: %s" % (imageName))
            imagePath = xenrt.TEC().lookup("CD_PATH_%s" % self.host.productVersion.upper(), 
                                           xenrt.TEC().lookup('CD_PATH', 'xe-phase-1'))
            self.host.cd = xenrt.TEC().getFile(os.path.join(imagePath, imageName), imageName)
        if not self.host.cd:
            raise xenrt.XRTError("No CD image supplied.")
        xenrt.checkFileExists(self.host.cd)

    def setupExtraInstallPackages(self, extracds, suppackcds): 
        workdir = xenrt.TEC().getWorkdir()
        # If we have any extra CDs, copy the extra packages as well
        if extracds:
            ecds = extracds
        else:
            ecds = self.host.getDefaultAdditionalCDList()

        if ecds:
            for ecdi in string.split(ecds, ","):
                ecd = xenrt.TEC().getFile("xe-phase-1/%s" % (os.path.basename(ecdi)),
                                          os.path.basename(ecdi))
                if not ecd:
                    raise xenrt.XRTError("Couldn't find %s." % (ecdi))
                xenrt.TEC().logverbose("Using extra CD %s" % (ecd))
                emount = xenrt.MountISO(ecd)
                emountpoint = emount.getMount()
                self.packdir.copyIn("%s/packages.*" % (emountpoint))
                emount.unmount()

        # If we have any supplemental pack CDs, copy their contents as well
        # and contruct the XS-REPOSITORY-LIST file
        if suppackcds is None:
            suppackcds = self.host.getSupplementalPackCDs()
        supptarballs = xenrt.TEC().lookup("SUPPLEMENTAL_PACK_TGZS", None)
        suppdirs = xenrt.TEC().lookup("SUPPLEMENTAL_PACK_DIRS", None)
        
        if suppackcds or supptarballs or suppdirs:
            repofile = "%s/XS-REPOSITORY-LIST" % (workdir)
            repo = file(repofile, "w")
            dstfile = "%s/XS-REPOSITORY-LIST" % self.packdir.dir
            if os.path.exists(dstfile):
                os.chmod(dstfile, os.stat(dstfile)[stat.ST_MODE]|stat.S_IWUSR)
                f = file(dstfile, "r")
                repo.write(f.read())
                f.close()
            if supptarballs:
                for supptar in supptarballs.split(","):
                    tarball = xenrt.TEC().getFile(supptar)
                    if not tarball:
                        tarball = xenrt.TEC().getFile("xe-phase-1/%s" % (supptar))
                    if not tarball:
                        tarball = xenrt.TEC().getFile("xe-phase-2/%s" % (supptar))
                    if not tarball:
                        raise xenrt.XRTError("Couldn't find %s." % (supptar))
                    xenrt.TEC().comment("Using supplemental pack tarball %s." % (tarball))
                    tdir = xenrt.TEC().tempDir()
                    xenrt.util.command("tar -zxf %s -C %s" % (tarball, tdir)) 
                    mnt = xenrt.MountISO("%s/*.iso" % (tdir))
                    pi = file("%s/post-install.sh" % (tdir)).read()
                    self.extrapi += "%s\n\n" % re.sub("exit.*", "", pi)
                    self.packdir.copyIn("%s/*" % (mnt.getMount()),
                                   "/packages.%s/" % (os.path.basename(tarball).strip(".tgz")))
                    repo.write("packages.%s\n" % (os.path.basename(tarball).strip(".tgz")))
            if suppackcds:    
                for spcdi in string.split(suppackcds, ","):
                    # Try a fetch from the inputdir first
                    spcd = xenrt.TEC().getFile(spcdi)
                    if not spcd:
                        # Try the local test inputs
                        spcd = "%s/suppacks/%s" % (\
                            xenrt.TEC().lookup("TEST_TARBALL_ROOT"),
                            os.path.basename(spcdi))
                        if not os.path.exists(spcd):
                            raise xenrt.XRTError(\
                                "Supplemental pack CD not found locally or "
                                "remotely: %s" % (spcdi))
                            
                    xenrt.TEC().comment("Using supplemental pack CD %s" % (spcd))
                    spmount = xenrt.MountISO(spcd)
                    spmountpoint = spmount.getMount()
                    self.packdir.copyIn("%s/*" % (spmountpoint),
                                   "/packages.%s/" % (os.path.basename(spcdi)))
                    repo.write("packages.%s\n" % (os.path.basename(spcdi)))
            if suppdirs:
                for sd in string.split(suppdirs, ","):
                    tgz = xenrt.TEC().getFile(sd)
                    if not tgz:
                        raise xenrt.XRTError("Supplemental pack dir not found: %s" % sd)
                    t = xenrt.resources.TempDirectory()
                    xenrt.util.command("tar -C %s -xvzf %s" % (t.dir, tgz))
                    self.packdir.copyIn("%s/*" % t.dir, "/packages.%s/" % os.path.basename(tgz))
                    repo.write("packages.%s\n" % (os.path.basename(tgz)))
                    t.remove()
            repo.close()
            self.packdir.copyIn(repofile)
            xenrt.TEC().copyToLogDir(repofile,
                                     target="XS-REPOSITORY-LIST-%s" % self.host.getName())

    def setupInstallUefiPxe(self, pxe, mountpoint, answerfileUrl):
        serport = self.host.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.host.lookup("SERIAL_CONSOLE_BAUD", "115200")
        comport = str(int(serport) + 1)
        
        xen_extra_args = self.host.lookup("XEN_EXTRA_ARGS", None)
        xen_extra_args_user = self.host.lookup("XEN_EXTRA_ARGS_USER", None)
        if xen_extra_args_user:
            xen_extra_args_user = string.replace(xen_extra_args_user, ",", " ")
        dom0_extra_args = self.host.lookup("DOM0_EXTRA_ARGS", None)
        dom0_extra_args_user = self.host.lookup("DOM0_EXTRA_ARGS_USER", None)
        
        pxe.installBootloader("%s/boot/grubx64.efi" % mountpoint, self.host.machine)
        pxe.copyIn("%s/boot/xen.gz" % mountpoint)
        pxe.copyIn("%s/boot/vmlinuz" % mountpoint)
        pxe.copyIn("%s/install.img" % mountpoint)

        xenargs = []
        xenargs.append("watchdog")
        xenargs.append("com%s=%s,8n1" % (comport, serbaud))
        xenargs.append("console=com%s,vga" % (comport))
        xenargs.append("dom0_mem=1024M,max:1024M")
        xenargs.append("dom0_max_vcpus=2")
        xenargs.append("crashkernel=128M@32M")
        xenargs.append("cpuid_mask_xsave_eax=0")
        if xen_extra_args:
            xenargs.append(xen_extra_args)
        if xen_extra_args_user:
            xenargs.append(xen_extra_args_user)

        dom0args = []
        dom0args.append("hpet=disable")
        dom0args.append("net.ifnames=0")
        dom0args.append("biosdevname=0")
        dom0args.append("xencons=hvc")
        dom0args.append("console=hvc0")
        if dom0_extra_args:
            dom0args.append(dom0_extra_args)
        if dom0_extra_args_user:
            dom0args.append(dom0_extra_args_user)
        if self.host.installnetwork:
            mac = self.host.getNICMACAddress(self.host.listSecondaryNICs(self.host.installnetwork)[0])
        else:
            mac = self.host.lookup("MAC_ADDRESS", None)
        if mac:
            dom0args.append("answerfile_device=%s" % (mac))
        if self.host.lookup("FORCE_NIC_ORDER", False, boolean=True):
            nics = [0]
            nics.extend(self.host.listSecondaryNICs())
            for n in nics:
                dom0args.append("map_netdev=eth%u:s:%s" % (n, self.host.getNICMACAddress(n)))
        dom0args.append("install")
        if not xenrt.TEC().lookup("OPTION_NO_ANSWERFILE", False, boolean=True):
            dom0args.append("rt_answerfile=%s" % (answerfileUrl))
        if xenrt.TEC().lookup("OPTION_BASH_SHELL", False, boolean=True):
            dom0args.append("bash-shell")

        installEntry = """
            multiboot2 %s/xen.gz %s
            module2 %s/vmlinuz %s
            module2 %s/install.img
        """ % (pxe.tftpPath(), " ".join(xenargs), pxe.tftpPath(), " ".join(dom0args), pxe.tftpPath())


        pxe.addGrubEntry("carboninstall", installEntry, default=True)
       
        # Default local boot entry - will be replaced with a boot label if we can retrieve one
        localEntry = """
            root=(%s,gpt4)
            chainloader /EFI/xenserver/grubx64.efi
        """
        pxe.addGrubEntry("local", localEntry)

        pxefile = pxe.writeOut(self.host.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))

    def setupInstallPxe(self, pxe, mountpoint, answerfileUrl):
        serport = self.host.lookup("SERIAL_CONSOLE_PORT", "0")
        serbaud = self.host.lookup("SERIAL_CONSOLE_BAUD", "115200")
        comport = str(int(serport) + 1)
        
        xen_extra_args = self.host.lookup("XEN_EXTRA_ARGS", None)
        xen_extra_args_user = self.host.lookup("XEN_EXTRA_ARGS_USER", None)
        if xen_extra_args_user:
            xen_extra_args_user = string.replace(xen_extra_args_user, ",", " ")
        dom0_extra_args = self.host.lookup("DOM0_EXTRA_ARGS", None)
        dom0_extra_args_user = self.host.lookup("DOM0_EXTRA_ARGS_USER", None)
        
        
        use_mboot_img = xenrt.TEC().lookup("USE_MBOOT_IMG", False, boolean=True)
        
        pxe.copyIn("%s/boot/*" % (mountpoint))
        instimg = xenrt.TEC().lookup("CUSTOM_INSTALL_IMG", None)
        if instimg:
            pxe.copyIn(xenrt.TEC().getFile(instimg), "install.img")
        else:
            pxe.copyIn("%s/install.img" % (mountpoint))
        # For NetScaler SDX
        if use_mboot_img:
            imagePath = xenrt.TEC().lookup("CD_PATH_%s" % self.host.productVersion.upper(), 
                                           xenrt.TEC().lookup('CD_PATH', 'xe-phase-1'))
            pxe.copyIn(xenrt.TEC().getFile(os.path.join(imagePath, "mboot.img")), "mboot.img")
        # Set the boot files and options for PXE
        if self.host.lookup("PXE_NO_SERIAL", False, boolean=True):
            pxe.setSerial(None,None)
        else:
            pxe.setSerial(serport, serbaud)
        if self.host.lookup("PXE_NO_PROMPT", False, boolean=True):
            pxe.setPrompt("0")
        chain = self.host.getChainBoot()
        if chain:
            pxe.addEntry("local", boot="chainlocal", options=chain)
        else:
            pxe.addEntry("local", boot="local")
        if use_mboot_img:
            pxecfg = pxe.addEntry("carboninstall", default=1, boot="mbootimg")
        else:
            pxecfg = pxe.addEntry("carboninstall", default=1, boot="mboot")
        xenfiles = glob.glob("%s/boot/xen*" % (mountpoint))
        xenfiles.extend(glob.glob("%s/boot/xen.gz" % (mountpoint)))
        if len(xenfiles) == 0:
            raise xenrt.XRTError("Could not find a xen* file to boot")
        xenfile = os.path.basename(xenfiles[-1])
        kernelfiles = glob.glob("%s/boot/vmlinuz*" % (mountpoint))
        if len(kernelfiles) == 0:
            raise xenrt.XRTError("Could not find a vmlinuz* file to boot")
        kernelfile = os.path.basename(kernelfiles[-1])

        if use_mboot_img:
            pass
        else:
            pxecfg.mbootSetKernel(xenfile)
            pxecfg.mbootSetModule1(kernelfile)
            pxecfg.mbootSetModule2("install.img")
        
        pxecfg.mbootArgsKernelAdd("watchdog")
        pxecfg.mbootArgsKernelAdd("com%s=%s,8n1" % (comport, serbaud))
        pxecfg.mbootArgsKernelAdd("console=com%s,vga" % (comport))
        pxecfg.mbootArgsKernelAdd("dom0_mem=1024M,max:1024M")
        pxecfg.mbootArgsKernelAdd("dom0_max_vcpus=2")
        if xen_extra_args:
            pxecfg.mbootArgsKernelAdd(xen_extra_args)
            xenrt.TEC().warning("Using installer extra Xen boot args %s" %
                                (xen_extra_args))
        if xen_extra_args_user:
            pxecfg.mbootArgsKernelAdd(xen_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Xen boot args %s" %
                                (xen_extra_args_user))
        
        pxecfg.mbootArgsModule1Add("root=/dev/ram0")
        if self.host.special.has_key("dom0 uses hvc") and \
               self.host.special["dom0 uses hvc"]:
            pxecfg.mbootArgsModule1Add("console=tty0")
            pxecfg.mbootArgsModule1Add("xencons=hvc")
            pxecfg.mbootArgsModule1Add("console=hvc0")
        else:
            pxecfg.mbootArgsModule1Add("console=tty0")
            pxecfg.mbootArgsModule1Add("console=ttyS%s,%sn8" %
                                       (serport, serbaud))
        pxecfg.mbootArgsModule1Add("ramdisk_size=65536")
        pxecfg.mbootArgsModule1Add("install")
        
        if not xenrt.TEC().lookup("OPTION_NO_ANSWERFILE", False, boolean=True):
            pxecfg.mbootArgsModule1Add("rt_answerfile=%s" % (answerfileUrl))
        
        pxecfg.mbootArgsModule1Add("output=ttyS0")

        pxecfg.mbootArgsModule1Add("net.ifnames=0")
        pxecfg.mbootArgsModule1Add("biosdevname=0")

        if self.host.installnetwork:
            mac = self.host.getNICMACAddress(self.host.listSecondaryNICs(self.host.installnetwork)[0])
        else:
            mac = self.host.lookup("MAC_ADDRESS", None)
        if mac:
            pxecfg.mbootArgsModule1Add("answerfile_device=%s" % (mac))
        if self.host.lookup("FORCE_NIC_ORDER", False, boolean=True):
            nics = [0]
            nics.extend(self.host.listSecondaryNICs())
            for n in nics:
                pxecfg.mbootArgsModule1Add("map_netdev=eth%u:s:%s" % (n, self.host.getNICMACAddress(n)))
        if dom0_extra_args:
            pxecfg.mbootArgsModule1Add(dom0_extra_args)
            xenrt.TEC().warning("Using installer extra Dom0 boot args %s" %
                                (dom0_extra_args))
        if dom0_extra_args_user:
            pxecfg.mbootArgsModule1Add(dom0_extra_args_user)
            xenrt.TEC().warning("Using installer user extra Dom0 boot args %s"
                                % (dom0_extra_args_user))
        if xenrt.TEC().lookup("OPTION_BASH_SHELL", False, boolean=True):
            pxecfg.mbootArgsModule1Add("bash-shell")

        if self.host.bootLun:
            pxecfg.mbootArgsModule1Add("use_ibft")
            xenrt.TEC().logverbose("Booting RAM disk Linux to discover NIC PCI locations")
            try:
                self.host.bootRamdiskLinux()
            except Exception, e:
                xenrt.TEC().logverbose("Couldn't boot RAM disk Linux to discover NIC PCI locations: %s" % str(e))
                raise xenrt.XRTError("Failed to boot RAM disk Linux to discover NIC PCI locations")
            pxe.clearISCSINICs()
            for b in self.host.bootNics:
                mac = self.host.getNICMACAddress(b)
                # Find the PCI bus, device and function from sysfs, using the MAC
                device = self.host.execdom0("grep -li \"%s\" /sys/class/net/*/address | cut -d \"/\" -f 5" % mac).strip()
                pcilocation = self.host.execdom0("grep PCI_SLOT_NAME /sys/class/net/%s/device/uevent | cut -d \"=\" -f 2" % device).strip()
                m = re.match("[0-9a-fA-F]{4}:([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-9a-fA-F])", pcilocation)
                bus = int(m.group(1), 16)
                device = int(m.group(2), 16)
                function = int(m.group(3), 16)

                # IBFT spec for PCI device is:
                #   8 Bits: PCI Bus
                #   5 Bits: PCI Device
                #   3 Bits: PCI Function
                ibftpci = bus*256 + device*8 + function
                pxe.addISCSINIC(b, ibftpci)

        ssh_pw = xenrt.TEC().lookup("TEST_INSTALLER_SSHPW", None)
        if ssh_pw:
            pxecfg.mbootArgsModule1Add("sshpassword=%s"%ssh_pw)
        #elif not xenrt.TEC().lookup("NO_INSTALLER_SSH", False, boolean=True):
        #    # Enable SSH into the installer to aid debug if installations fail
        #    pxecfg.mbootArgsModule1Add("sshpassword=%s" % self.host.password)
        
        if self.host.mpathRoot:
            pxecfg.mbootArgsModule1Add("device_mapper_multipath=enabled")

        # Set up PXE for installer boot
        pxefile = pxe.writeOut(self.host.machine)
        pfname = os.path.basename(pxefile)
        xenrt.TEC().copyToLogDir(pxefile,target="%s.pxe.txt" % (pfname))
        if self.host.bootLun:
            ipxefile = pxe.writeISCSIConfig(self.host.machine)
            ipfname = os.path.basename(ipxefile)
            xenrt.TEC().copyToLogDir(ipxefile,target="%s.ipxe.txt" % (ipfname))

    def createInstallAnswerfile(self,
                                primarydisk,
                                guestdisks,
                                interfaces,
                                source,
                                nameserver,
                                ntpserver,
                                hostname,
                                installSRType,
                                timezone,
                                installnetwork):
        # Create the installer answerfile
        guestdiskconfig = ""
        interfaceconfig = ""
        otherconfigs = ""
        
        workdir = xenrt.TEC().getWorkdir()
        # If we use multipathed root disk, but want to put the local SR on a local disk, we need to set this up manually
        self.firstBootSRInfo = None
        if self.host.mpathRoot and guestdisks != [primarydisk]: 
            defaultSRType = self.host.lookup("DEFAULT_SR_TYPE", "lvm")
            if installSRType:
                self.firstBootSRInfo = (guestdisks[0], installSRType)
            else:
                self.firstBootSRInfo = (guestdisks[0], self.host.lookup("INSTALL_SR_TYPE", defaultSRType))
            guestdisks = []
        
        if not self.upgrade:
            if xenrt.TEC().lookup('SR_ON_PRIMARY_DISK', True, boolean=True):
                pass
            else:
                guestdisks = list(set(guestdisks) - set([primarydisk]))
            for g in guestdisks:
                guestdiskconfig = guestdiskconfig + \
                                  ("<guest-disk>%s</guest-disk>\n" % (g))
            for i in interfaces:
                name, enabled, proto, ip, netmask, gateway, protov6, ip6, gw6 = i
                mac = None
                if name:
                    # If name is specifed then use the named interface
                    pass
                else:
                    # Otherwise use the configured default
                    if self.host.INSTALL_INTERFACE_SPEC == "MAC":
                        if installnetwork:
                            mac = self.host.getNICMACAddress(self.host.listSecondaryNICs(installnetwork)[0])
                        else:
                            mac = self.host.lookup("MAC_ADDRESS", None)
                    if not mac:
                        name = self.host.getDefaultInterface()
                if mac:
                    spec = "hwaddr=\"%s\"" % (mac.lower())
                else:
                    spec = "name=\"%s\"" % (name)

                params = {'spec' : spec, 
                          'enabled' : enabled, 
                          'proto' : proto, 
                          'ip': ip, 
                          'netmask': netmask, 
                          'gateway' : gateway,
                          'protov6' : protov6, 
                          'ip6' : ip6, 
                          'gw6' : gw6}
                
                static_ipv6_info = ""
                if proto == "static":
                    if protov6 == "static":
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.host.ipv6_mode = protov6
                        self.host.setIP(params['ip6'])
                        static_ipv6_info = "<ipv6>%(ip6)s/64</ipv6>\n  <gatewayv6>%(gw6)s</gatewayv6>" % params
                    elif protov6 in set(["none", "dhcp", "autoconf"]):
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.host.ipv6_mode = protov6
                    else:
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s">""" % params
                    
                    params.update({'admin_interface' : admin_interface, 'static_ipv6_info': static_ipv6_info})
                    
                    interfaceconfig = interfaceconfig + """<interface %(spec)s enabled="%(enabled)s" proto="%(proto)s">
  <ip>%(ip)s</ip>
  <subnet-mask>%(netmask)s</subnet-mask>
  <gateway>%(gateway)s</gateway>
</interface>
%(admin_interface)s
  <ip>%(ip)s</ip>
  <subnet-mask>%(netmask)s</subnet-mask>
  <gateway>%(gateway)s</gateway>
  %(static_ipv6_info)s
</admin-interface>
""" % params 
                else:
                    if protov6 == "static":
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.host.ipv6_mode = protov6
                        self.host.setIP(params['ip6'])
                        static_ipv6_info = "<ipv6>%(ip6)s/64</ipv6>\n  <gatewayv6>%(gw6)s</gatewayv6>" % params
                    elif protov6 in set(["none", "dhcp", "autoconf"]):
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s" protov6="%(protov6)s">""" % params
                        self.host.ipv6_mode = protov6
                    else:
                        admin_interface = """<admin-interface %(spec)s enabled="%(enabled)s" proto="%(proto)s">""" % params

                    static_ipv6_info = static_ipv6_info + "\n"
                    params.update({'admin_interface' : admin_interface, 'static_ipv6_info': static_ipv6_info})
                    
                    interfaceconfig = interfaceconfig + '<interface %(spec)s enabled="%(enabled)s" proto="%(proto)s"/>\n%(admin_interface)s\n  %(static_ipv6_info)s</admin-interface>' % params 
            if self.host.ipv6_mode == "autoconf":
                self.host.setIP(self.host.getIPv6AutoconfAddress())
            elif self.host.ipv6_mode == "dhcp":
                (_, _, _, ip6, _) = self.host.getNICAllocatedIPAddress(0, also_ipv6=True)
                self.host.setIP(ip6)
            elif self.host.ipv6_mode == "none" or self.host.ipv6_mode is None:
                self.host.use_ipv6 = False
                
            if nameserver:
                otherconfigs = otherconfigs + ("<nameserver>%s</nameserver>\n" %
                                               (nameserver))
            if ntpserver:
                otherconfigs = otherconfigs + ("<ntp-servers>%s</ntp-servers>\n" %
                                               (ntpserver))
            if hostname:
                otherconfigs = otherconfigs + ("<hostname>%s</hostname>\n" %
                                               (hostname))

        if self.upgrade:
            ansfile = "%s/%s-upgrade.xml" % (workdir, self.host.getName())
        else:
            ansfile = "%s/%s-install.xml" % (workdir, self.host.getName())
        ans = file(ansfile, "w")
        if source == "nfs":
            url = self.packdir.getMountURL("")
            purl = self.pidir.getURL("post-install-script-%s" % (self.host.getName()))
            furl = self.pidir.getURL("install-failed-script-%s" % (self.host.getName()))
            pextra = ""
        else:
            url = self.packdir.getURL("")
            purl = self.pidir.getURL("post-install-script-%s" % (self.host.getName()))
            furl = self.pidir.getURL("install-failed-script-%s" % (self.host.getName()))
            pextra = ""
        if self.upgrade:
            installationExtras = " mode=\"upgrade\""
        else:
            installationExtras = ""
            # If a local SR type if not specified then normally we don't
            # specify it in the answerfile and rely on the product default.
            # We can override this behaviour by specifying a default in
            # DEFAULT_SR_TYPE. This can still be overriden by the srtype
            # argument to this method or the INSTALL_SR_TYPE variable
            # (generally used in a sequence file)
            defaultSRType = self.host.lookup("DEFAULT_SR_TYPE", None)
            if installSRType:
                srtype = installSRType
            else:
                srtype = self.host.lookup("INSTALL_SR_TYPE", defaultSRType)
            if srtype:
                installationExtras = installationExtras + " srtype='%s'" % (srtype)
        if self.upgrade:
            storage = """<existing-installation>%s</existing-installation>""" \
                % (primarydisk)
        else:
            primarydiskconfig = """<primary-disk gueststorage="no">%s</primary-disk>""" % primarydisk
            storage = """%s
%s
""" % (primarydiskconfig, guestdiskconfig)
        if self.upgrade:
            rpassword = ""
        else:
            rpassword = "<root-password>%s</root-password>" % (self.host.password)

        network_backend = xenrt.TEC().lookup("NETWORK_BACKEND", None)
        if network_backend:
            otherconfigs = otherconfigs + ("<network-backend>%s</network-backend>\n"
                                           % (network_backend))

        if xenrt.TEC().lookup("CC_ENABLE_SSH", False, boolean=True):
            otherconfigs = otherconfigs + "<service name=\"sshd\" state=\"enabled\"/>\n"

        driverDisk = xenrt.TEC().lookup("DRIVER_DISK", None)
        if driverDisk:
            driverWebDir = xenrt.WebDirectory()
            xenrt.TEC().logverbose("Using driver disk %s" % driverDisk)
            cd = xenrt.TEC().getFile(driverDisk)
            if not cd:
                raise xenrt.XRTError("Cannot find driver disk %s" % driverDisk)
            driverMount = xenrt.MountISO(cd)
            driverMountPoint = driverMount.getMount()
            driverWebDir.copyIn("%s/*" % driverMountPoint)
            otherconfigs += ("<driver-source type=\"url\">%s</driver-source>\n" % \
                             (driverWebDir.getURL("")))

        anstext = """<?xml version="1.0"?>
<installation%s>
%s
%s
%s
<source type="%s">%s</source>
<timezone>%s</timezone>
<post-install-script%s>%s</post-install-script>
<install-failed-script>%s</install-failed-script>
%s
</installation>
""" % (installationExtras,
       storage,
       interfaceconfig,
       rpassword,
       source,
       url,
       timezone,
       pextra,
       purl,
       furl,
       otherconfigs)
        ans.write(anstext)
        ans.close()
        self.packdir.copyIn(ansfile)
        xenrt.TEC().copyToLogDir(ansfile)
        
        return os.path.basename(ansfile)

    def createPostInstallFiles(self, uefi):
        workdir = xenrt.TEC().getWorkdir()

        postInstall = []
        if uefi:
            postInstall.append(self.forceUefiBootViaPxe)
            postInstall.append(self.postInstallSendBootLabel)
        postInstall.append(self.postInstallBootMods)
        postInstall.append(self.postInstallSSHKey)
        postInstall.append(self.postInstallXapiTweak)
        postInstall.append(self.postInstallRedoLog)
        postInstall.append(self.postInstallUnplugDom0vCPUs)
        postInstall.append(self.postInstallBlacklistDrivers)
        postInstall.append(self.postInstallSSH)
        postInstall.append(self.postInstallDom0MemPool)
        postInstall.append(self.postInstallNonDebugXen)
        postInstall.append(self.postInstallFirstBootSR)
        postInstall.append(self.postInstallOverlay)
        postInstall.append(self.postInstallUsbWipe)
        postInstall.append(self.postInstallWriteCookie)
        postInstall.append(self.postInstallStopSSH)
        postInstall.append(self.postInstallSignal)

        pifile = "%s/post-install-script-%s" % (workdir,self.host.getName())
        pitext = """#!/bin/bash
#
# This post-install-script hook calls this with the argument being the
# mount point of the dom0 filesystem

set -x

cd $1

%s
""" % ("\n".join(postInstall))
        with open(pifile, "w") as pi:
            pi.write(pitext)
        
        self.pidir.copyIn(pifile)
        xenrt.TEC().copyToLogDir(pifile)

        # Create a script to run on install failure (on builds that
        # support this)
        fifile = "%s/install-failed-script-%s" % (workdir,self.host.getName())
        fitext = """#!/bin/bash

# The arguments to this script have changed in Bodie. It will be called
# for both a successful and failed install. The first (and only) command line
# argument is 0 for success and 1 for failure.

if [ "$1" = "0" ]; then
    
    %s
    
    # Bodie mode, this was a successful installation
    echo "Successful install, not running fail commands."
    exit 0
fi

# Signal XenRT that we've failed
mkdir /tmp/xenrttmpmount
mount -t nfs %s /tmp/xenrttmpmount
echo "Failed install" > /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
cat /proc/partitions >> /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
for i in /sys/block/*/device/vendor; do echo $i; cat $i; done >> /tmp/failedinstall
for i in /sys/block/*/device/model; do echo $i; cat $i; done >> /tmp/failedinstall
echo "==============" >> /tmp/failedinstall
if [ -x /opt/xensource/installer/report.py ]; then
  /opt/xensource/installer/report.py file:///tmp/xenrttmpmount/
fi
cat /tmp/failedinstall /tmp/install-log > /tmp/xenrttmpmount/.xenrtsuccess
umount /tmp/xenrttmpmount

# if we have atexit=shell specified, we should exit 
grep 'atexit=shell' /proc/cmdline &> /dev/null && exit 0

# Now stop here so we don't boot loop
while true; do
    sleep 30
done
""" % (self.extrapi, self.signaldir.getMountURL(""))
        with open(fifile, "w") as fi:
            fi.write(fitext)
        fi.close()
        self.pidir.copyIn(fifile)
        xenrt.TEC().copyToLogDir(fifile)
        

