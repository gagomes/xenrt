#
# XenRT: Test harness for Xen and the XenServer product family.
#
# Testcases for verifying XenServer Boot from SAN  features.
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xml.dom.minidom, re, string, copy, time, os, random 
import xenrt, xenrt.lib.xenserver

try:
    import NaServer
except ImportError:
    # The NetApp SDK is not always available so ignore import errors.
    pass

class _HostInstall(xenrt.TestCase):

    ROOTDISK_MPATH_COUNT = 4
    ISCSI_SR_MPATH_COUNT = 2
    DEFAULT_PATH_COUNT   = 1

    def hostInstall(self):
        self.host = xenrt.lib.xenserver.createHost(id=0)
        self.getLogsFrom(self.host)
        self.host.check()
        self.host.enableAllFCPorts()

    def checkHost(self):
        pass

    def createVM(self):
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        self.smokeVM()

    def smokeVM(self):
        self.guest.start()
        self.guest.suspend()
        self.guest.resume()
        self.guest.reboot()
        self.guest.shutdown()

    def rebootHost(self):
        self.host.reboot()
        self.checkHost()

    def run(self, arglist=None):

        if self.runSubcase("hostInstall", (), "Host", "Install") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("checkHost", (), "Host", "Check") != \
               xenrt.RESULT_PASS:
            return
        if "postInstall" in dir(self):
            if self.runSubcase("postInstall", (), "Host", "PostInstall") != \
                   xenrt.RESULT_PASS:
                return
        if self.runSubcase("createVM", (), "Initial", "VMCheck") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("rebootHost", (), "Host", "Reboot") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("smokeVM", (), "PostReboot", "VMCheck") != \
               xenrt.RESULT_PASS:
            return
        if "finalCheck" in dir(self):
            if self.runSubcase("finalCheck", (), "Host", "FinalCheck") != \
                   xenrt.RESULT_PASS:
                return
        
class TC9352(_HostInstall):
    """Install to a server with a boot disk on a SAN via an Emulex HBA."""

    ISCSI_SR_MULTIPATHED = True

    def postInstall(self):
        # Create a FC SR on another LUN
        self.fcLun = xenrt.HBALun([self.host])
        self.fcSRScsiid = self.fcLun.getID()
        self.fcSR = xenrt.lib.xenserver.FCStorageRepository(self.host, "fc")
        self.fcSR.create(self.fcLun)
        self.host.addSR(self.fcSR, default=True)
        
        # Create an iSCSI SR
        self.iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "iscsi TC9352")
        self.iscsiSR.create(subtype="lvm", multipathing=self.ISCSI_SR_MULTIPATHED)
        self.host.addSR(self.iscsiSR)

        pbd = self.host.parseListForUUID("pbd-list",
                            "sr-uuid",
                            self.iscsiSR.uuid,
                            "host-uuid=%s" % (self.host.getMyHostUUID()))
        
        self.iscsiSRScsiid = self.host.genParamGet("pbd", pbd, "device-config", "SCSIid")
    
    def getVendorFromDM(self, blockDevice):
        slaves = self.host.execdom0("ls /sys/block/%s/slaves/"
                                    % blockDevice).strip().split()
        pddev = slaves[0]
        dvendor = self.host.execdom0(
            "cat /sys/block/%s/slaves/%s/device/vendor"
            % (blockDevice, pddev)).strip()
        return dvendor
        

    def checkHost(self):
        # Check the root disk is on a LUN delivered by HBA
        primarydisk = self.host.getInventoryItem("PRIMARY_DISK")
        deviceinfo = self.host.execdom0("ls -l %s" % primarydisk)
        if deviceinfo[0] == 'l':
            # Is a link, possibly udev mode
            pddev = self.host.execdom0("readlink -f %s"
                                       % (primarydisk)).strip()
            pddev = pddev[5:]
            if pddev.startswith("dm-"):
                dvendor = self.getVendorFromDM(pddev)
            else:
                dvendor = self.host.execdom0("cat /sys/block/%s/device/vendor"
                                             % (pddev)).strip()
        elif deviceinfo[0] == 'b':
            # Is block device, possibly devmapper mode
            minornumber = int(deviceinfo.strip().split()[5])
            dvendor = self.getVendorFromDM("dm-%d" % minornumber)
        else:
            raise xenrt.XRTError("Unkown device mapping mode",
                                 data = deviceinfo)
        if not dvendor in ["DGC", "NETAPP"]:
            raise xenrt.XRTError("Installation primary disk is not a SAN LUN",
                                 "%s -> %s is '%s'" %
                                 (primarydisk, pddev, dvendor))
        
    def createVM(self):
        # create a guest on the FC SR
        self.fcGuest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.fcGuest)
        self.fcGuest.shutdown()
        
        # create a guest on the iSCSI SR
        self.iscsiGuest = self.host.createGenericLinuxGuest(sr=self.iscsiSR.uuid)
        self.uninstallOnCleanup(self.iscsiGuest)
        self.iscsiGuest.shutdown()
        
        self.smokeVM()
        
    def smokeVM(self):
        # smoke test the guest on the FC SR
        self.fcGuest.start()
        self.fcGuest.suspend()
        self.fcGuest.resume()
        self.fcGuest.reboot()
        self.fcGuest.shutdown()
        
        # smoke test the guest on the iSCSI SR
        self.iscsiGuest.start()
        self.iscsiGuest.suspend()
        self.iscsiGuest.resume()
        self.iscsiGuest.reboot()
        self.iscsiGuest.shutdown()
    
    def finalCheck(self):
        # Check the FC VM is on the FC SR
        vbds = self.fcGuest.listVBDUUIDs("Disk")
        for vbd in vbds:
            sruuid = self.host.getVBDSR(vbd)
            if sruuid != self.fcSR.uuid:
                raise xenrt.XRTError("Test VM not on the FC SR", "On %s" % (sruuid))
        
        # Check the iSCSI VM is on the iSCSI SR
        vbds = self.iscsiGuest.listVBDUUIDs("Disk")
        for vbd in vbds:
            sruuid = self.host.getVBDSR(vbd)
            if sruuid != self.iscsiSR.uuid:
                raise xenrt.XRTError("Test VM not on the iSCSI SR", "On %s" % (sruuid))
                
    def postRun(self):
        if self.iscsiSR:
            self.iscsiSR.release()
        if self.fcSR:
            self.fcSR.forget() # which eventually release the LUN as well.
                
class TC12059(TC9352):
    """Install to a server with a boot disk on a SAN via Emulex HBAs with multipath root disk and single path SR"""
    
    ISCSI_SR_MULTIPATHED = False
    
    def prepare(self, arglist=None):
        xenrt.TEC().config.setVariable("OPTION_ROOT_MPATH", "enabled") 
    
    def postInstall(self):
        self.scsiid = string.split(self.host.lookup("OPTION_CARBON_DISKS", None), "scsi-")[1]
        TC9352.postInstall(self)
        
        self.checkHostMultipathConfigKeys()
        
        self.checkMultipathing()

    def checkHostMultipathConfigKeys(self):
        # check host multipath config keys
        try:
            self.host.paramGet("other-config", "multipathed")
        except Exception, e:
            if re.search("Key multipathed not found in map", str(e)):
                raise xenrt.XRTFailure("other-config:multipathed host config key is missing")
            raise

        try:
            self.host.paramGet("other-config", "mpath-boot")
        except Exception, e:
            if re.search("Key mpath-boot not found in map", str(e)):
                raise xenrt.XRTFailure("other-config:mpath-boot host config key is missing")
            raise

    def checkMultipathing(self):
        # check host multipathing
        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)

        if not mp.has_key(self.scsiid):
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u, the default path to root disk" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, self.DEFAULT_PATH_COUNT))
        
        if len(mp[self.scsiid]) != self.ROOTDISK_MPATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))
            
        if mp.has_key(self.iscsiSRScsiid) and len(mp[self.iscsiSRScsiid]) != self.DEFAULT_PATH_COUNT:
            raise xenrt.XRTFailure("Expecting the default %u/%u paths active for ISCSI SR, found %u" %
                                        (self.DEFAULT_PATH_COUNT, self.ISCSI_SR_MPATH_COUNT, len(mp[self.iscsiSRScsiid])))

class TC12061(TC12059):
    """Install to a server with a boot disk on a SAN via Emulex HBAs with multipathing with primary path down"""
    
    ISCSI_SR_MULTIPATHED = True

    def hostInstall(self):
        TC12059.hostInstall(self)
        
        # disable primary path
        self.host.disableFCPort(0)
        time.sleep(60)

        # Re-install the host
        try:
            self.host.uuid = None
            self.host.dom0uuid = None
            self.host.reinstall()
            time.sleep(180)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Failure during reinstall: %s" % (e.reason))
    
    def postRun(self):
        # Ensure primary path restored (it should be already.)
        self.host.enableFCPort(0)
        time.sleep(60)
    
    def checkMultipathing(self):
        # check host multipathing
        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)

        if mp.has_key(self.scsiid) and len(mp[self.scsiid]) != self.ROOTDISK_MPATH_COUNT/2:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u" %
                                        (self.ROOTDISK_MPATH_COUNT/2, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))

        if not mp.has_key(self.iscsiSRScsiid):
            raise xenrt.XRTFailure("Expecting %u/%u paths active for ISCSI SR, found %u, the default path to SR" %
                                        (self.ISCSI_SR_MPATH_COUNT, self.ISCSI_SR_MPATH_COUNT, self.DEFAULT_PATH_COUNT))

        if len(mp[self.iscsiSRScsiid]) != self.ISCSI_SR_MPATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for ISCSI SR, found %u" %
                                        (self.ISCSI_SR_MPATH_COUNT, self.ISCSI_SR_MPATH_COUNT, len(mp[self.iscsiSRScsiid])))

    def finalCheck(self):
        TC12059.finalCheck(self)
        
        # now restore primary path
        self.host.enableFCPort(0)
        time.sleep(60)

        # check host multipathing
        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)

        if not mp.has_key(self.scsiid):
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u, the default path to root disk" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, self.DEFAULT_PATH_COUNT))

        if len(mp[self.scsiid]) != self.ROOTDISK_MPATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))

        if not mp.has_key(self.iscsiSRScsiid):
            raise xenrt.XRTFailure("Expecting %u/%u paths active for ISCSI SR, found %u, the default path to SR" %
                                        (self.ISCSI_SR_MPATH_COUNT, self.ISCSI_SR_MPATH_COUNT, self.DEFAULT_PATH_COUNT))

        if len(mp[self.iscsiSRScsiid]) != self.ISCSI_SR_MPATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for ISCSI SR, found %u" %
                                        (self.ISCSI_SR_MPATH_COUNT, self.ISCSI_SR_MPATH_COUNT, len(mp[self.iscsiSRScsiid])))

class TC12062(TC12059):
    """Install to a server with a boot disk on a SAN via Emulex HBAs with multipathing with secondary path down"""
    
    ISCSI_SR_MULTIPATHED = False
    
    def hostInstall(self):
        TC12059.hostInstall(self)
        
        # disable secondary path
        self.host.disableFCPort(1)
        time.sleep(60)

        # Re-install the host
        try:
            self.host.uuid = None
            self.host.dom0uuid = None
            self.host.reinstall()
            time.sleep(180)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Failure during reinstall: %s" % (e.reason))
    
    def postRun(self):
        # Ensure secondary path restored (it should be already.)
        self.host.enableFCPort(1)
        time.sleep(60)
    
    def checkMultipathing(self):
        # check host multipathing
        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)

        if mp.has_key(self.scsiid) and len(mp[self.scsiid]) != self.ROOTDISK_MPATH_COUNT/2:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u" %
                                        (self.ROOTDISK_MPATH_COUNT/2, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))

        if mp.has_key(self.iscsiSRScsiid) and len(mp[self.iscsiSRScsiid]) != self.DEFAULT_PATH_COUNT:
            raise xenrt.XRTFailure("Expecting the default %u/%u paths active for ISCSI SR, found %u" %
                                        (self.DEFAULT_PATH_COUNT, self.ISCSI_SR_MPATH_COUNT, len(mp[self.iscsiSRScsiid])))

    def finalCheck(self):
        TC12059.finalCheck(self)

        # now restore secondary path
        self.host.enableFCPort(1)
        time.sleep(60)

        # check host multipathing
        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)

        if not mp.has_key(self.scsiid):
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u, the default path to root disk" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, self.DEFAULT_PATH_COUNT))

        if len(mp[self.scsiid]) != self.ROOTDISK_MPATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk, found %u" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))

        if len(mp[self.iscsiSRScsiid]) != self.ISCSI_SR_MPATH_COUNT/2:
            raise xenrt.XRTFailure("Expecting the default %u/%u paths active for ISCSI SR, found %u" %
                                        (self.DEFAULT_PATH_COUNT, self.ISCSI_SR_MPATH_COUNT, len(mp[self.iscsiSRScsiid])))

class TC12209(TC9352):
    """Install to a server with a boot disk on a SAN via Emulex HBAs without multipathing turned on"""
    
    ISCSI_SR_MULTIPATHED = False
    
    def prepare(self, arglist=None):
        xenrt.TEC().config.setVariable("OPTION_ROOT_MPATH", "") 

    def postInstall(self):
        self.scsiid = string.split(self.host.lookup("OPTION_CARBON_DISKS", None), "scsi-")[1]
        TC9352.postInstall(self)
        
        self.checkMultipathing()

    def checkMultipathing(self):
        # check host multipathing
        mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
        
        if mp.has_key(self.scsiid) and len(mp[self.scsiid]) != self.DEFAULT_PATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for root disk (default path to root disk), found %u" %
                                            (self.DEFAULT_PATH_COUNT, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))
            
        if mp.has_key(self.iscsiSRScsiid) and len(mp[self.iscsiSRScsiid]) != self.DEFAULT_PATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active for ISCSI SR (default path to SR), found %u" %
                                            (self.DEFAULT_PATH_COUNT, self.ISCSI_SR_MPATH_COUNT, len(mp[self.iscsiSRScsiid])))

class TCXenServerRestore(xenrt.TestCase):
    def run(self, arglist=None):
        host = self.getDefaultHost()
        inventory1 = host.execdom0("cat /etc/xensource-inventory")
        newhost = host.upgrade(xenrt.TEC().lookup("PRODUCT_VERSION", None))
        inventory2 = newhost.execdom0("cat /etc/xensource-inventory")
        if sorted(inventory2.splitlines()) == sorted(inventory1.splitlines()):
            raise xenrt.XRTError("xensource-inventory didn't update after upgrade")
        newhost.restoreOldInstallation()
        inventory3 = host.execdom0("cat /etc/xensource-inventory")
        if sorted(inventory3.splitlines()) != sorted(inventory1.splitlines()):
            raise xenrt.XRTFailure("xensource-inventory didn't revert")

class TC18381(TC9352):
    """Verify that boot-disk on SAN is excluded from the list of available LUN/VDIs"""

    BWD_SUPP_PACK = "borehamwood-supp-pack.iso"
    BWD_RPM_REPO = 'xs:borehamwood-supp-pack'

    def rebootHost(self):
        xenrt.TEC().logverbose("rebootHost() function is not implemented for this test.")

    def createVM(self):
        xenrt.TEC().logverbose("createVM() function is not implemented for this test.")

    def smokeVM(self):
        xenrt.TEC().logverbose("smokeVM() function is not implemented for this test.")

    def finalCheck(self):
        xenrt.TEC().logverbose("finalCheck() function is not implemented for this test.")

    def postRun(self):
        xenrt.TEC().logverbose("postRun() function is not implemented for this test.")

    def postInstall(self):

        # Borehamwood Supplemental Pack is integrated in Creedence. Install only for previous releases.
        if not isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            self.installBorehamwoodSuppPack()
        else: # Simply enable the pluggins in Creedence hosts.
            self.host.execdom0("/opt/xensource/sm/enable-borehamwood enable; exit 0")
            self.host.waitForXapi(600, desc="After enabling the borehamwood pluggins")

        # Find out the SCSID of the root disk on a LUN delivered by HBA
        primarydisk = self.host.getInventoryItem("PRIMARY_DISK") # '/dev/disk/by-id/scsi-360a98000534b4f50476f707a63743464'
        r = re.search(r"/dev/disk/by-id/scsi-(\S+)", primarydisk)
        primarydiskSCSID = r.group(1)
        xenrt.TEC().logverbose("Boot from SAN, SCSID of the root disk on a LUN delivered by HBA %s" % primarydiskSCSID)

        # Create RawHBA SR.
        xenrt.TEC().logverbose("Creating RawHBA (LUN/VDI) SR")
        self.rawHBASR = xenrt.lib.xenserver.RawHBAStorageRepository(self.host, "RawHBASR")
        self.rawHBASR.create()
        self.host.addSR(self.rawHBASR, default=True)

        # It is important to scan RawHBA SR at this moment.
        self.rawHBASR.scan()
        self.sruuid = self.rawHBASR.uuid
        self.vdiuuids = self.rawHBASR.listVDIs()

        # Check if root disk on a LUN delivered by HBA is listed as LUN/VDI.
        for lunPerVDI in self.vdiuuids:
            vdiNameLabel = self.host.genParamGet("vdi", lunPerVDI, "name-label")
            xenrt.TEC().logverbose("LunPerVDI UUID: %s - name-label: %s" %
                                                                (lunPerVDI, vdiNameLabel))
            if vdiNameLabel:
                if (vdiNameLabel == primarydiskSCSID):
                    raise xenrt.XRTFailure("RawHBASR contains the boot-disk: %s on SAN as one of the LUN/VDI." %
                                                                                                        vdiNameLabel)
                # Anything other than netApp LUN. e.g. SATA_SAMSUNG_HE502HJ_S2B6J90B900947
                elif not vdiNameLabel.startswith("360a98000"):
                    xenrt.TEC().warning("A special disk: %s attached to the host is seen as LUN/VDI." %
                                                                                                vdiNameLabel)
            else:
                raise xenrt.XRTFailure("The name-label of LUN/VDI: %s is reported to be empty." %
                                                                                            lunPerVDI)

    def installBorehamwoodSuppPack(self):
        """Installs Borehamwood Supplemental Pack"""

        xenrt.TEC().logverbose("Installing Borehamwood Supplemental Pack ...")

        # Retrieve Borehamwood Supplemental Pack
        bwdSuppPack = xenrt.TEC().getFile("xe-phase-2/%s" %
                                            (self.BWD_SUPP_PACK),self.BWD_SUPP_PACK)
        try:
            xenrt.checkFileExists(bwdSuppPack)
        except:
            raise xenrt.XRTError("Borehamwood Supplemental Pack: %s is not found in xe-phase-2" %
                                                                                    self.BWD_SUPP_PACK)

        # Copy Borehamwood Supplemental Pack to Controller.
        hostPath = "/tmp/%s" % (self.BWD_SUPP_PACK)
        sh = self.host.sftpClient()
        try:
            sh.copyTo(bwdSuppPack,hostPath)
        finally:
            sh.close()

        # Install Borehamwood Supplemental Pack.
        try:
            self.host.execdom0("xe-install-supplemental-pack /tmp/%s" % (self.BWD_SUPP_PACK))
        except:
            raise xenrt.XRTFailure("Could not install Borehamwood Supplemental Pack: %s on host %s " %
                                                                                (self.BWD_SUPP_PACK, self.host))

        # Verify Borehamwood Supplemental Pack is installed.
        if self.BWD_RPM_REPO not in self.host.execdom0("ls /etc/xensource/installed-repos/"):
            raise xenrt.XRTFailure("Borehamwood RPM package %s is not installed on the host %s" %
                                                                                (self.BWD_RPM_REPO, self.host))

        # Restart Xapi
        xenrt.TEC().logverbose("Restarting Xapi after installing Borehamwood Supplemental Pack ...")
        self.host.execdom0("/opt/xensource/bin/xe-toolstack-restart")
        self.host.waitForXapi(900, desc="Waiting for Xapi response after installing Borehamwood Supplemental Pack ...")

class TCISCSIBoot(xenrt.TestCase): # TC20845
    """Install to a server with a iSCSI boot disk on a SAN via Native Linux """
    
    def prepare(self, arglist):
        self.iscsiHost = self.getHost("RESOURCE_HOST_1")
        self.iscsiHost.createNetworkTopology("""<NETWORK>
        <PHYSICAL network="NSEC">
            <NIC />
            <MANAGEMENT />
        </PHYSICAL>
    </NETWORK>""")
        self.bootLun = xenrt.ISCSINativeLinuxLun(self.iscsiHost, sizeMB = 50*xenrt.KILO)

        # Handling CA-121665
        self.lun = xenrt.ISCSINativeLinuxLun(self.iscsiHost, sizeMB = 60*xenrt.KILO)
        xenrt.TEC().registry.resourcePut("ISCSISRLUN", self.lun)

    def run(self, arglist):
        self.host = xenrt.lib.xenserver.createHost(id=0, iScsiBootLun=self.bootLun, iScsiBootNets=["NSEC"])
        self.getLogsFrom(self.host)

class TCISCSIMultipathBoot(xenrt.TestCase): #TC20851
    """Install to a server with a multipathed iSCSI boot disk on a SAN via Native Linux"""

    def prepare(self, arglist):
        self.iscsiHost = self.getHost("RESOURCE_HOST_1")
        self.iscsiHost.createNetworkTopology("""<NETWORK>
        <PHYSICAL network="NSEC">
            <NIC />
            <MANAGEMENT />
        </PHYSICAL>
        <PHYSICAL network="IPRI">
            <NIC />
            <STORAGE />
        </PHYSICAL>
    </NETWORK>""")
        self.bootLun = xenrt.ISCSINativeLinuxLun(self.iscsiHost, sizeMB = 50*xenrt.KILO)
        
        # Handling CA-121665
        srlun = xenrt.ISCSINativeLinuxLun(self.iscsiHost, sizeMB = 60*xenrt.KILO)
        xenrt.TEC().registry.resourcePut("ISCSISRLUN", srlun)

    def run(self, arglist):
        self.host = xenrt.lib.xenserver.createHost(id=0, iScsiBootLun=self.bootLun, iScsiBootNets=["NSEC", "IPRI"])
        self.getLogsFrom(self.host)

class TC20846(xenrt.TestCase):
    """Create iSCSI SR on iSCSI booted machine, where the SR target is on same storage IP as the boot disk target"""

    def prepare(self, arglist):
        # Retrieving iSCSI LUN from registry for SR creation.
        self.lun = xenrt.TEC().registry.resourceGet("ISCSISRLUN")

        # Obtaining the iSCSI booted machine.
        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self, arglist):
        # Creating iSCSI SR.
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, 
                                                "iscsi-sr-on-same-storage-as-boot-disk")
        iscsiSR.create(self.lun, subtype="lvm", multipathing=False, noiqnset=True)

class TC20847(xenrt.TestCase):
    """Create iSCSI SR on iSCSI booted machine, where the SR target is on a different storage IP, but same subnet as the boot disk target"""

    def prepare(self, arglist):
        # Obtaining the iSCSI booted machine.
        self.host = self.getHost("RESOURCE_HOST_0")
        self.net = self.host.getNICNetworkName(self.host.bootNics[0])

    def run(self, arglist):
        # Create LVMoISCSI SR delivered by a temporary LUN on the XenRT controller, and connect to it using the boot network.
        lun = xenrt.ISCSITemporaryLun(100)
        lun.setNetwork(self.net)
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, 
                                                "iscsi-sr-on-different-storage-but-same-subnet-as-boot-disk")
        iscsiSR.create(lun, subtype="lvm", findSCSIID=True, noiqnset=True, multipathing=False)

class TC20848(xenrt.TestCase):
    """Create iSCSI SR on iSCSI booted machine, where the SR target is on a different storage IP and different subnet as the boot disk target"""

    def prepare(self, arglist):
        # Obtaining the iSCSI booted machine.
        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self, arglist):
         # Create an iSCSI SR.
        if self.host.getNICNetworkName(self.host.bootNics[0]) == "NPRI":
            raise xenrt.XRTError("This test relies on the boot net being not NPRI")
        # Create a controller LUN and connect to it on NPRI
        lun = xenrt.ISCSITemporaryLun(100)
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, 
                                            "iscsi-sr-on-different-storage-and-different-subnet-as-boot-disk")
        iscsiSR.create(lun, subtype="lvm", findSCSIID=True, multipathing=False, noiqnset=True)

class TC20849(xenrt.TestCase):
    """Create NFS SR on iSCSI booted machine, where the SR target is on same storage IP as the boot disk target"""

    def prepare(self, arglist):
        # Obtaining the Native Linux server to install NFS Share.
        self.iscsiHost = self.getHost("RESOURCE_HOST_1")

        # Obtaining the iSCSI booted machine.
        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self, arglist):
        # Set up NFS on the Native Linux machine.
        self.iscsiHost.execcmd("chkconfig nfs on")
        self.iscsiHost.execcmd("service rpcbind start")
        self.iscsiHost.execcmd("service nfs start")
 
        # Create a dir and export the shared directory.
        self.iscsiHost.execcmd("mkdir /nfsShare")
        self.iscsiHost.execcmd("echo '/nfsShare *(sync,rw,no_root_squash,no_subtree_check)'"
                        " > /etc/exports")
        self.iscsiHost.execcmd("exportfs -a")

        # Create the nfs SR on the host.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(self.host,
                                                    "nfs-sr-on-same-storage-as-boot-disk")
        nfsSR.create(self.iscsiHost.getIP(),"/nfsShare")

class TC20850(xenrt.TestCase):
    """Create NFS SR on iSCSI booted machine, where the SR target is on a different storage IP and subnet as the boot disk target"""

    def prepare(self, arglist):
        # Obtaining the iSCSI booted machine.
        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self, arglist):
        nfs = xenrt.resources.NFSDirectory()
        nfsDir = xenrt.command("mktemp -d %s/nfsXXXX" % (nfs.path()), strip = True)
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(self.host, 
                                                "nfs-sr-on-different-subnet-as-boot-disk")
        server, path = nfs.getHostAndPath(os.path.basename(nfsDir))
        nfsSR.create(server, path)

class TCISCSIMultipathScenarios(xenrt.TestCase):
    """Base class for obtaining the hosts to test multipath failover scenarios"""

    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_0")

        xenrt.TEC().logverbose("Number of boot NICS = %d" % len(self.host.bootNics))
        xenrt.TEC().logverbose("Number of active paths to boot LUN = %d" % self.countActivePaths())

        if len(self.host.bootNics) != 2:
            raise xenrt.XRTError("Host does not have 2 boot NICs")
        if self.countActivePaths() != 2:
            raise xenrt.XRTError("Host does not have 2 paths to boot LUN")
    
    def failPath(self, pathindex):
        """Fail the iSCSI path based on path index"""
        
        xenrt.TEC().logverbose("Failing the path %d" % pathindex)
        
        mac = self.host.getNICMACAddress(self.host.bootNics[pathindex])
        self.host.disableNetPort(mac)

    def recoverPath(self, pathindex):
        """Recover the iSCSI path based on path index"""
        
        xenrt.TEC().logverbose("Recovering the the path %d" % pathindex)
        
        mac = self.host.getNICMACAddress(self.host.bootNics[pathindex])
        self.host.enableNetPort(mac)

    def countActivePaths(self):
        """Count the number of active paths"""
        
        xenrt.TEC().logverbose("Coutning the number of paths on host ...")
        
        return len(self.host.getMultipathInfo(onlyActive=True)[self.host.bootLun.getID()])

    def waitForPathCount(self, expected):
        """Waiting for a brief time to obtain the desired multipath count"""
        
        xenrt.TEC().logverbose("Waiting for 180 seconds before reporting the number of active paths ...")
        
        deadline = xenrt.util.timenow() + 180
        while xenrt.util.timenow() < deadline:
            time.sleep(10)
            count = self.countActivePaths()
            if count == expected:
                return

        raise xenrt.XRTFailure("Did not get expected path count - expected %d, got %d" % (expected, count))

    def checkHost(self):
    
        xenrt.TEC().logverbose("Checking the host ...")
        
        self.host.execdom0("dd if=/dev/zero of=/root/pathtest oflag=direct bs=1M count=20")
        self.host.execdom0("dd if=/root/pathtest of=/dev/null")

class TC20852(TCISCSIMultipathScenarios):
    """Create multipathed iSCSI SR on multipathed iSCSI booted machine, where the SR target is on same storage IP as the boot disk target"""

    def run(self, arglist):
        # Retrieving iSCSI LUN from registry for SR creation.
        self.lun = xenrt.TEC().registry.resourceGet("ISCSISRLUN")

        # Creating multipathed iSCSI SR.
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, 
                                                "multipathed-iscsi-sr-on-same-storage-as-boot-disk")
        iscsiSR.create(self.lun, subtype="lvm", multipathing=True, noiqnset=True)

class TCISCSIMultipathFailOnBoot(TCISCSIMultipathScenarios):
    PATH_INDEX=None
    
    def run(self, arglist):
        # Fail the path
        self.failPath(self.PATH_INDEX)
        # Check the host is healthy
        self.checkHost()
        # Check it only has one path
        self.waitForPathCount(1)
        # Reboot the host
        self.host.reboot(timeout=3600)
        # Check one path is present
        self.waitForPathCount(1)
        # Recover the path and reboot (we don't expect it to come back after boot)
        self.recoverPath(self.PATH_INDEX)
        self.host.reboot()
        # And check we now have 2 paths
        self.waitForPathCount(2)

class TC20853(TCISCSIMultipathFailOnBoot):
    """Bring down the first path at boot on multipathed iSCSI booted machine"""
    PATH_INDEX=0

class TC20854(TCISCSIMultipathFailOnBoot):
    """Bring down the second path at boot on multipathed iSCSI booted machine"""
    PATH_INDEX=1

class TC20855(TCISCSIMultipathScenarios):
    """Carry out failover of alternate paths on multipathed iSCSI booted machine"""
    def run(self, arglist):
        for i in range(100):
            path = random.randint(0,1)
            self.failPath(path)
            self.checkHost()
            self.waitForPathCount(1)
            self.checkHost()
            self.recoverPath(path)
            self.checkHost()
            self.waitForPathCount(2)
            self.checkHost()


class TCUCSISCSIMultipathScenarios(TCISCSIMultipathScenarios):
    """Base class for UCS iSCSI multipathed boot scenarios"""

    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.iscsiHost = self.getHost("RESOURCE_HOST_1")
        self.scsiid = string.split(self.host.lookup("OPTION_CARBON_DISKS", None), "scsi-")[1]

        ip = self.host.lookup(["UCSISCSI", "TARGET_ADDRESS"], None)
        username = self.host.lookup(["UCSISCSI", "TARGET_USERNAME"], None)
        password = self.host.lookup(["UCSISCSI", "TARGET_PASSWORD"], None)
        self._server = NaServer.NaServer(ip, 1, 0)
        self._server.set_admin_user(username, password)

        xenrt.TEC().logverbose("Number of active paths to boot LUN = %d" % self.countActivePaths())
        if self.countActivePaths() != 2:
            raise xenrt.XRTError("Host does not have 2 paths to boot LUN")

    def controlPath(self, pathindex, state):
        ifname = self.host.lookup(["UCSISCSI", "VLAN%u" % (pathindex + 1), "INTERFACE"], None)
        res = self._server.invoke("net-ifconfig-set", "interface-config-info", """
<interface-name>%s</interface-name>
<ipspace-name>default-ipspace</ipspace-name>
<is-enabled>%s</is-enabled>
""" % (ifname, state))
        if res.results_errno() != 0:
            raise Exception("Failed to control port: " + str(res.results_reason()))

    def failPath(self, pathindex):
        """Fail the iSCSI path based on path index"""

        xenrt.TEC().logverbose("Failing the path %d" % pathindex)
        self.controlPath(pathindex, "false")

    def recoverPath(self, pathindex):
        """Recover the iSCSI path based on path index"""

        xenrt.TEC().logverbose("Recovering the the path %d" % pathindex)
        self.controlPath(pathindex, "true")

    def countActivePaths(self):
        """Count the number of active paths"""

        xenrt.TEC().logverbose("Coutning the number of paths on host ...")
        return len(self.host.getMultipathInfo(onlyActive=True)[self.scsiid])

    def postRun(self):
        xenrt.TEC().logverbose("Ensuring paths are up after testcase")
        self.recoverPath(0)
        self.recoverPath(1)

class TC27173(TCUCSISCSIMultipathScenarios):
    """Create multipathed iSCSI SR on multipathed UCS iSCSI booted machine"""

    def run(self, arglist):
        bridges = []

        for i in (1, 2):
            vlan = int(self.host.lookup(["UCSISCSI", "VLAN%u" % i, "NUMBER"], None))
            nic = self.iscsiHost.getDefaultInterface()
            vbridge = self.iscsiHost.createNetwork()
            bridges.append(vbridge)
            pifuuid = self.iscsiHost.createVLAN(vlan, vbridge, nic)

        self.bootLun = xenrt.resources.ISCSIVMLun(hostIndex=1, sizeMB=50000, bridges=bridges)

        # Creating multipathed iSCSI SR.
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,
                                                "multipathed-iscsi-sr")
        iscsiSR.create(self.bootLun, subtype="lvm", multipathing=True, noiqnset=True, findSCSIID=True)

class TCUCSISCSIMultipathFailOnBoot(TCUCSISCSIMultipathScenarios):
    PATH_INDEX=None

    def run(self, arglist):
        # Fail the path
        self.failPath(self.PATH_INDEX)
        # Check the host is healthy
        self.checkHost()
        # Check it only has one path
        self.waitForPathCount(1)
        # Reboot the host
        self.host.reboot(timeout=3600)
        # Check one path is present
        self.waitForPathCount(1)
        # Recover the path and reboot (we don't expect it to come back after boot)
        self.recoverPath(self.PATH_INDEX)
        self.host.reboot()
        # And check we now have 2 paths
        self.waitForPathCount(2)

class TC27174(TCUCSISCSIMultipathFailOnBoot):
    """Bring down the first path at boot on multipathed UCS iSCSI booted machine"""
    PATH_INDEX=0

class TC27175(TCUCSISCSIMultipathFailOnBoot):
    """Bring down the second path at boot on multipathed UCS iSCSI booted machine"""
    PATH_INDEX=1

class TC27176(TCUCSISCSIMultipathScenarios):
    """Carry out failover of alternate paths on multipathed UCS iSCSI booted machine"""
    def run(self, arglist):
        for i in range(10):
            path = random.randint(0,1)
            self.failPath(path)
            self.checkHost()
            self.waitForPathCount(1)
            self.checkHost()
            self.recoverPath(path)
            self.checkHost()
            self.waitForPathCount(2)
            self.checkHost()

class TC27246(xenrt.TestCase):
    """Install to a server with a multipathed iSCSI boot disk on a Powervault"""

    def override(self, key, value):
        resource_host = "RESOURCE_HOST_0"
        machine = xenrt.TEC().lookup(resource_host, resource_host)
        xenrt.TEC().config.setVariable(["HOST_CONFIGS", machine, key], value)

    @staticmethod
    def productVersionFromInputDir(inputDir):
        fn = xenrt.TEC().getFile("%s/xe-phase-1/globals" % inputDir, "%s/globals" % inputDir)
        if fn:
            for line in open(fn).xreadlines():
                match = re.match('^PRODUCT_VERSION="(.+)"', line)
                if match:
                    hosttype = xenrt.TEC().lookup(["PRODUCT_CODENAMES", match.group(1)], None)
                    if hosttype:
                        return hosttype
        return xenrt.TEC().lookup("PRODUCT_VERSION", None)

    def lookup(self, key):
        resource_host = "RESOURCE_HOST_0"
        machine = xenrt.TEC().lookup(resource_host, resource_host)
        m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
        hosttype = self.productVersionFromInputDir(xenrt.TEC().getInputDir())
        host = xenrt.lib.xenserver.hostFactory(hosttype)(m,
                                                     productVersion=hosttype)
        return host.lookup(key, None)

    def run(self, arglist):
        carbon_disks = self.lookup(["UCSISCSI", "CARBON_DISKS"])
        guest_disks = self.lookup(["UCSISCSI", "GUEST_DISKS"])
        self.override("OPTION_CARBON_DISKS", carbon_disks)
        self.override("OPTION_GUEST_DISKS", guest_disks)
        self.override("LOCAL_SR_POST_INSTALL", "no")
        self.override("DOM0_EXTRA_ARGS", "use_ibft")
        self.host = xenrt.lib.xenserver.createHost(id=0, installnetwork="NSEC")

        scsiid = string.split(carbon_disks, "scsi-")[1]
        if len(self.host.getMultipathInfo(onlyActive=True)[scsiid]) != 2:
            raise xenrt.XRTError("Host does not have 2 paths to boot LUN")

class TC27247(xenrt.TestCase):
    """Create an iSCSI SR on iSCSI booted machine, where the SR target is on a
    different storage IP and the same subnet as the boot disk."""

    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.iscsiHost = self.getHost("RESOURCE_HOST_1")

    def run(self, arglist):
        self.bootLun = xenrt.resources.ISCSIVMLun(hostIndex=1, sizeMB=50000)
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "iscsi-sr")
        iscsiSR.create(self.bootLun, subtype="lvm", noiqnset=True, findSCSIID=True)

class TC27248(xenrt.TestCase):
    """Create NFS SR on iSCSI booted machine, where the SR target is on a
    different storage IP and the same subnet as the boot disk."""

    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.nfsHost = self.getHost("RESOURCE_HOST_1")

    def run(self, arglist):
        self.nfsHost.execcmd("service nfs start")
        self.nfsHost.execcmd("iptables -F")

        # Create a dir and export the shared directory.
        self.nfsHost.execcmd("mkdir /nfsShare")
        self.nfsHost.execcmd("echo '/nfsShare *(sync,rw,no_root_squash,no_subtree_check)'"
                        " > /etc/exports")
        self.nfsHost.execcmd("exportfs -a")

        # Create the nfs SR on the host.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(self.host, "nfs-sr")
        nfsSR.create(self.nfsHost.getIP(),"/nfsShare")

class TC27298(xenrt.TestCase):
    """Install to a server with a iSCSI boot disk on a SAN using iPXE."""

    @staticmethod
    def productVersionFromInputDir(inputDir):
        fn = xenrt.TEC().getFile("%s/xe-phase-1/globals" % inputDir, "%s/globals" % inputDir)
        if fn:
            for line in open(fn).xreadlines():
                match = re.match('^PRODUCT_VERSION="(.+)"', line)
                if match:
                    hosttype = xenrt.TEC().lookup(["PRODUCT_CODENAMES", match.group(1)], None)
                    if hosttype:
                        return hosttype
        return xenrt.TEC().lookup("PRODUCT_VERSION", None)

    def lookup(self, key):
        resource_host = "RESOURCE_HOST_0"
        machine = xenrt.TEC().lookup(resource_host, resource_host)
        m = xenrt.PhysicalHost(xenrt.TEC().lookup(machine, machine))
        hosttype = self.productVersionFromInputDir(xenrt.TEC().getInputDir())
        host = xenrt.lib.xenserver.hostFactory(hosttype)(m,
                                                     productVersion=hosttype)
        return host.lookup(key, None)

    def prepare(self, arglist):
        initiator_name = self.lookup(["EQLISCSI", "INITIATOR_NAME"])
        target_address = self.lookup(["EQLISCSI", "BOOTLUN", "TARGET_ADDRESS"])
        target_name = self.lookup(["EQLISCSI", "BOOTLUN", "TARGET_NAME"])
        self.bootLun = xenrt.ISCSILunSpecified("%s/%s/%s" % (initiator_name, target_name, target_address))
        self.bootLun.scsiid = self.lookup(["EQLISCSI", "BOOTLUN", "SCSIID"])

    def run(self, arglist):
        self.host = xenrt.lib.xenserver.createHost(id=0, iScsiBootLun=self.bootLun, iScsiBootNets=["NPRI"], installnetwork="NSEC")

class TC27299(xenrt.TestCase):
    """Create iSCSI SR on iSCSI booted machine, where the SR target is on same storage IP as the boot disk target"""

    def prepare(self, arglist):
        # Obtain the iSCSI booted machine.
        self.host = self.getHost("RESOURCE_HOST_0")

        initiator_name = self.host.lookup(["EQLISCSI", "INITIATOR_NAME"], None)
        target_address = self.host.lookup(["EQLISCSI", "SRLUN", "TARGET_ADDRESS"], None)
        target_name = self.host.lookup(["EQLISCSI", "SRLUN", "TARGET_NAME"], None)
        self.lun = xenrt.ISCSILunSpecified("%s/%s/%s" % (initiator_name, target_name, target_address))
        self.lun.scsiid = self.host.lookup(["EQLISCSI", "SRLUN", "SCSIID"], None)

    def run(self, arglist):
        # Create iSCSI SR.
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,
                                                "iscsi-sr-on-same-storage-as-boot-disk")
        iscsiSR.create(self.lun, subtype="lvm", multipathing=False, noiqnset=True)

class TC27300(xenrt.TestCase):
    """Create iSCSI SR on iSCSI booted machine, where the SR target is on a different storage IP and the same subnet as the boot disk target"""

    def prepare(self, arglist):
        # Obtain the iSCSI booted machine.
        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self, arglist):
        # Create a controller LUN and connect to it
        lun = xenrt.ISCSITemporaryLun(100)
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,
                                            "iscsi-sr-on-different-storage-same-subnet-as-boot-disk")
        iscsiSR.create(lun, subtype="lvm", findSCSIID=True, multipathing=False, noiqnset=True)

class TC27301(xenrt.TestCase):
    """Create iSCSI SR on iSCSI booted machine, where the SR target is on a different storage IP and subnet as the boot disk target"""

    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.iscsiHost = self.getHost("RESOURCE_HOST_1")

    def run(self, arglist):
        # Create an IP address on IPRI
        self.host.createNetworkTopology("""
            <NETWORK>
                <PHYSICAL network="NSEC">
                    <NIC />
                    <VLAN network="IPRI">
                        <STORAGE />
                    </VLAN>
                    <MANAGEMENT />
                </PHYSICAL>
            </NETWORK>
        """)

        vlan = self.host.getVLAN("IPRI")[0]
        nic = self.iscsiHost.getDefaultInterface()
        vbridge = self.iscsiHost.createNetwork()
        pifuuid = self.iscsiHost.createVLAN(vlan, vbridge, nic)
        ip = self.iscsiHost.enableIPOnPIF(pifuuid)
        xenrt.TEC().registry.resourcePut("VLANIP", ip)

        self.bootLun = xenrt.resources.ISCSIVMLun(hostIndex=1, sizeMB=50000, bridges=[vbridge])

        # Creating multipathed iSCSI SR.
        iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,
                                                "iscsi-sr-on-different-storage-different-subnet-as-boot-disk")
        iscsiSR.create(self.bootLun, subtype="lvm", noiqnset=True, findSCSIID=True)

class TC27302(xenrt.TestCase):
    """Create NFS SR on iSCSI booted machine, where the SR target is on a
    different storage IP and a different subnet as the boot disk."""

    def prepare(self, arglist):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.nfsHost = self.getHost("RESOURCE_HOST_1")

    def run(self, arglist):
        self.nfsHost.execcmd("service nfs start")
        self.nfsHost.execcmd("iptables -F")

        # Create a dir and export the shared directory.
        self.nfsHost.execcmd("mkdir /nfsShare")
        self.nfsHost.execcmd("echo '/nfsShare *(sync,rw,no_root_squash,no_subtree_check)'"
                        " > /etc/exports")
        self.nfsHost.execcmd("exportfs -a")

        # Create the nfs SR on the host.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(self.host, "nfs-sr")
        ip = xenrt.TEC().registry.resourceGet("VLANIP")
        nfsSR.create(ip, "/nfsShare")
