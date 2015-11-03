# XenRT: Test harness for Xen and the XenServer product family
#
# Test cases for Lun Per VDI features.
#
# Copyright (c) 2012 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, xenrt.lib.xenserver, string, re, time
from xenrt.lazylog import step, comment, log, warning
from xenrt.lib.xenserver.dr import *

class LunPerVDI(xenrt.TestCase):
    """Defines a base class for all the LUN/VDI testcases"""

    CLEANUP = True
    DELETE_GUEST = True
    REMOVE_SR = True
    DESTROY_VOLUME = True

    WINDISTRO = "ws08r2-x64"
    LINDISTRO = "rhel56"
    DISTRO =  "oel62"

    class _VdiUpdateMode(object): Add, Remove = range(2) 

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.pool = None
        self.hosts = []
        self.guests = []
        self.sr = None
        
        self.sruuid = None
        self.vdiuuids = []
        self.volumes = {} # is a dictionary of luns.
        self.pathName = "/vol"
        self.initiatorGroupName = None
        self.preExistingLuns = []
        
        #Locked until gec is executed!
        
    def _createInitiators(self):
        return dict(zip(self.hosts, [h.getFCWWPNInfo() for h in self.hosts]))

    def prepare(self, arglist=[]):

        # MSCI customer use the following distros.
        # 2003 R2 x64, 2008 x86, 2008 x64, 2008 R2 x64, 2012 x64, HPC 2008 x64, HPC 2008 R2 x64
        # OEL 5.x x86, OEL 5.x x64, OEL 6.x x64, RHEL 5.x x86, RHEL 5.x x64, RHEL 6.x x64
        for arg in arglist:
            if arg.startswith('distro'):
                self.DISTRO = arg.split('=')[1]
            if arg.startswith('lindistro'):
                self.LINDISTRO = arg.split('=')[1]
            if arg.startswith('windistro'):
                self.WINDISTRO = arg.split('=')[1]

        # Lock storage resource and access storage manager library functions.
        self.netAppFiler = xenrt.StorageArrayFactory().getStorageArray(xenrt.StorageArrayVendor.NetApp,
                                                                        xenrt.StorageArrayType.FibreChannel)

        # Get all the hosts.
        self.hosts = [xenrt.TEC().registry.hostGet(hn) for hn in xenrt.TEC().registry.hostList()]
        self.hosts = list(set(self.hosts))
        self.hosts.sort()

        for host in self.hosts:
            host.scanScsiBus()
            host.enableMultipathing()
            
            # In Creedence, Borehamwood features are installed by default. However, it requires to enable it.
            # In other releases, installing the supplimental pack will enable Borehamwood features.
            if isinstance(host, xenrt.lib.xenserver.CreedenceHost):
                self.enableBorehamwood(host)

            self.checkForStaticLuns(host)
            self.getLogsFrom(host)

        # Setup initial storage configuration, 10 LUNs of size 10GB each.
        self.netAppFiler.provisionLuns(10, 10, self._createInitiators())
        map(lambda host : self._customiseXenServerTemplates(host), self.hosts)
        map(lambda host : host.scanScsiBus(), self.hosts)
        
    def enableBorehamwood(self, host):
        """Enable Borehamwood pluggins on host"""
        
        try:
           commandOutput = host.execdom0("/opt/xensource/sm/enable-borehamwood enable; exit 0")
        except:
            if re.search("Error: 17 [errno=File exists]", commandOutput):
                xenrt.TEC().logverbose("Borehamwood pluggins are already enabled on host %s" % host)
            elif re.search("RawHBASR symlink created", commandOutput) and re.search("toolstack restarted", commandOutput):
                xenrt.TEC().logverbose("Borehamwood pluggins are successfully enabled on host %s" % host)            
            else:
                raise xenrt.XRTFailure("Borehamwood pluggins are not enabled on host %s" % host)
 
    def checkForStaticLuns(self, host):
        """Check for any pre-existing LUNs on the host."""
        # This function must be run before creating the RawHBA SR to know the pre-existing LUNs on the host.
        self.preExistingLuns = host.execdom0("ls /dev/disk/by-scsid").strip().split("\n")
        self.preExistingLuns.sort()

        if len(self.preExistingLuns) > 0:
            xenrt.TEC().logverbose("%d pre-configured static lun(s) found on host %s are: %s " %
                                                (len(self.preExistingLuns), host, str(self.preExistingLuns)))
        else:
            xenrt.TEC().logverbose("There are no pre-configured static luns found on host %s" % host)

    def _customiseXenServerTemplates(self, host):
        """This function customise the XenServer tempaltes to support LUN/VDI guest installation"""

        xenrt.TEC().logverbose("Customising XenServer templates on host %s." % host)

        templateList = host.minimalList("template-list")
        for templateUUID in templateList:
            # Clear the disks parameter to chose LUN/VDI from the RawHBA SR.
            host.genParamSet("template", templateUUID, "other-config:disks", "<provision/>")

    def updateExtraLuns(self, lunIDs, mode):
        """This function updates the internal variables when extra LUNs are added to the test"""

        xenrt.TEC().logverbose("Updating internal class member variables for the mode = %s" % mode)

        for nameLabel in lunIDs:
            newVDIUUID = self.hosts[0].minimalList("vdi-list", args="name-label=%s" % nameLabel)
            if newVDIUUID:
                if (mode ==  self._VdiUpdateMode.Add):
                    self.vdiuuids = self.vdiuuids + newVDIUUID
                elif (mode == self._VdiUpdateMode.Remove):
                    
                    self.vdiuuids = [item for item in self.vdiuuids if item not in newVDIUUID]
                    # Need to destroy the VDI as per requirement.
                    # On re-scan it will not disappear, even if the luns are deleted.
                    self.hosts[0].getCLIInstance().execute("vdi-destroy", "uuid=%s" % newVDIUUID[0])
                else:
                    raise xenrt.XRTFailure("Unsupported mode in updateExtraLuns function.")
            else:
                raise xenrt.XRTFailure("VDIs not found for the newly added LUN [name-lable: %s] after the SR scan." % nameLabel)


    def checkLunsIntegrity(self):
        """Verifies the lun health status by directly contacting the storage array"""

        xenrt.TEC().logverbose("Checking mapped LUNs integrity after the RawBHA SR deletion.")

        for lun in self.netAppFiler.getLuns(): 
            # Check 2. Still mapped to iGroup?
            if not lun.isMapped():
                raise xenrt.XRTError("The LUN %s mapping status changed unexpectedly." % lun.getID())

            # Check 3. Still Online?
            if not lun.isOnline():
                raise xenrt.XRTError("The LUN %s online status changed unexpectedly." % lun.getID() )

            # Check 4. Share-state of the lun altered ?
            if (lun.sharedState() != xenrt.StorageArrayLun.ShareState.NotSet): 
                raise xenrt.XRTError("The LUN %s shared status changed unexpectedly: was %s." % (lun.getID(), str(lun.sharedState())))

            # Check 5. Size altered ? (more work to check unless required, for the time being as below.)
            if (lun.size() == 0):
                raise xenrt.XRTError("The LUN %s size: %d has changed unexpectedly." % (lun.getID(), lun.size()))

    def createSR(self):
        """Creates Raw LUN SR on the host"""

        xenrt.TEC().logverbose("Creating RawHBA (LUN/VDI SR)")

        self.sr = xenrt.lib.xenserver.RawHBAStorageRepository(self.hosts[0], "RawHBA")
        self.sr.create()
        # It is important to scan RawHBA SR at this moment.
        self.sr.scan()
        self.sruuid = self.sr.uuid
        self.vdiuuids = self.sr.listVDIs()

        # Exclude some of the statis VDIs in storage array.
        staticLunsVDIuuids = []
        for staticLunLabel in self.preExistingLuns:
            staticLunsVDIuuids = staticLunsVDIuuids + self.hosts[0].minimalList("vdi-list", args="name-label=%s" % staticLunLabel)
        self.vdiuuids = list(set(self.vdiuuids) - set(staticLunsVDIuuids))

    def deleteSR(self):
        """Deletes Raw LUN SR from the host"""

        xenrt.TEC().logverbose("Forgetting RawHBA (LUN/VDI SR)")

        self.hosts[0].forgetSR(self.sruuid)

        # 1. Check all the VDIs under the RawHBA are deleted from the host.
        unexpectedVDIList =[]
        for vdiuuid in self.vdiuuids:
            try:
                self.hosts[0].genParamGet("vdi", vdiuuid, "uuid")
                unexpectedVDIList.append(vdiuuid)
            except Exception, e:
                if re.search("The uuid you supplied was invalid", str(e)):
                    pass
                else:
                    raise

        if len(unexpectedVDIList) > 0:
            raise xenrt.XRTFailure("The VDIs under the RawHBA SR are not deleted while deleting the SR \n%s " %
                                    (("\n".join(map(str, unexpectedVDIList)))))

        # 2. Check sr-uuid for RawHBA sr-type is no longer seen in the system.
        try:
            sruuidFound = self.hosts[0].genParamGet("sr", self.sruuid, "uuid")
        except Exception, e:
            if re.search("The uuid you supplied was invalid", str(e)):
                pass
            else:
                raise
        else:
            raise xenrt.XRTFailure("The RawHBA SR object: %s is found even after SR forget." % sruuidFound)

        # 3. Following class variables need to be reset.
        self.sr = None
        self.sruuid = None
        self.vdiuuids = []

    def checkSR(self):
        """Performs check against each VDI against its associated LUN"""
        # 1. Verify it list all the assocaited LUNs as LUN/VDI (xe vdi-list)

        xenrt.TEC().logverbose("Checking RawHBA SR")

        vdiList = self.sr.listVDIs() # it is available from self.vdiuuids

        # Exclude the static test luns configured in array from consideration.
        excludeStaticVdis = []
        for vdi in vdiList:
            vdiNameLabel = self.hosts[0].genParamGet("vdi", vdi, "name-label")
            if not vdiNameLabel:
                raise xenrt.XRTFailure("The name-label of vdi uuid: %s is reported to be empty." % vdi)
            if (vdiNameLabel in self.preExistingLuns):
                excludeStaticVdis.append(vdi)
                
        xenrt.TEC().logverbose("Static VDIs to be excluded from testing: %s" % str(excludeStaticVdis))
        xenrt.TEC().logverbose("%d static VDIs" % len(excludeStaticVdis))
        vdiList = list(set(vdiList) - set(excludeStaticVdis))
        xenrt.TEC().logverbose("%d VDIs in vdi list, ignoring static luns" % len(vdiList))

        xenrt.TEC().logverbose("VDIs remaining after exclusion: %s" % str(vdiList))

        lunList = self.netAppFiler.getLuns()
        xenrt.TEC().logverbose("%d luns in the lunList" % len(lunList))
        xenrt.TEC().logverbose("lunList %s" % lunList)

        if (len(lunList) != len(vdiList)):
            xenrt.TEC().logverbose("The extra VDIs in the RawHBA SR are \n%s " %
                                    str(set(vdiList) - set(lunList)))
            xenrt.TEC().logverbose("The LUNs not present in the RawHBA SR are \n%s " %
                                    str(set(lunList) - set(vdiList)))
            raise xenrt.XRTFailure("Not all LUNs are presented as LUN/VDIs. Found %u new VDIs - expecting %u" %
                                 (len(vdiList), len(lunList)))

        # Also check the number of vdiuuids stored in object variable: self.vdiuuids
        if (set(self.vdiuuids) != set(vdiList)):
            raise xenrt.XRTFailure("VDI list did not match expected. Found %s - expecting %s" %
                                 (str(vdiList), str(self.vdiuuids)))

        for vdiuuid in vdiList:
            nameLabel = self.hosts[0].genParamGet("vdi", vdiuuid, "name-label").strip()
            virtualSize = int(self.hosts[0].genParamGet("vdi", vdiuuid, "virtual-size"))
            physicalSize = self.hosts[0].getVDIPhysicalSizeAndType(vdiuuid)[0]
            vdiType = self.hosts[0].getVDIPhysicalSizeAndType(vdiuuid)[1]

            xenrt.TEC().logverbose("vdi: %s, label: %s, virtual-size: %s, physical-size: %s, type: %s" % 
                                    (vdiuuid, nameLabel, virtualSize, physicalSize, vdiType))

            # 1. Verify the default name of each LUN/VDI is set to SCSIID its associated LUN.
            matchingLun = next((lun for lun in lunList if lun.getID() == nameLabel), None)
            
            if matchingLun == None:
                raise xenrt.XRTFailure("The VDI does not have an associated SCSI ID %s as name-label." % nameLabel)
                
            # 2. Verify each LUN/VDI reflects the size of the LUN.
            lunSize = matchingLun.size()
            if (lunSize != virtualSize):
                raise xenrt.XRTFailure("The VDI virtual size does not match with the LUN size %d." % lunSize)

            # 3. Check VDIs are of the expected physical size.
            if (lunSize != physicalSize):
                raise xenrt.XRTFailure("The VDI physical size does not match with the LUN size %d." % lunSize)

            # 4. Check VDIs are of the expected type.
            if (vdiType != "RAW"):
                raise xenrt.XRTFailure("Invalid VDI type for the LUN/VDI.")

    def enableLVMBasedStorage(self):
        """This function allows to add LVM based storage to a Borehamwood Enabled host"""

        for host in self.hosts:
            fileNames = host.execdom0("ls /etc/lvm").strip().split("\n")
            for fileName in fileNames:
                if fileName.startswith("lvm.conf") and fileName.endswith(".bak"):
                    host.execdom0("cp /etc/lvm/lvm.conf /etc/lvm/lvm.conf.tmp") 
                    host.execdom0("cp /etc/lvm/%s /etc/lvm/lvm.conf" % (fileName))
                    break
            host.restartToolstack()

    def disableLVMBasedStorage(self):
        """This function restricts to add LVM based storage to a Borehamwood Enabled host"""

        for host in self.hosts:
            fileNames = host.execdom0("ls /etc/lvm").strip().split("\n")
            for fileName in fileNames:
                if fileName.startswith("lvm.conf") and fileName.endswith(".tmp"):
                    host.execdom0("cp /etc/lvm/%s /etc/lvm/lvm.conf" % (fileName))
                    host.execdom0("rm /etc/lvm/lvm.conf.tmp") 
                    break
            host.restartToolstack()

    def postRun(self, arglist=None):
        """Cleanup before closing the test."""

        if self.CLEANUP:

            if self.DELETE_GUEST:
                # 2. Get rid of the temporary guest, if used in the test.
                if self.guests:
                    for guest in self.guests:
                        try:
                            try:
                                guest.shutdown(force=True)
                            except:
                                pass
                            guest.poll("DOWN", 120, level=xenrt.RC_ERROR)
                            guest.uninstall()
                        except Exception, e:
                            xenrt.TEC().warning("Exception while uninstalling temporary guest:%s %s" % (guest, str(e)))

            if self.REMOVE_SR:
                # 1. We created an LUN/VDI SR, lets try and forget it.
                try:
                    self.deleteSR()
                except Exception, e:
                    xenrt.TEC().warning("Exception while deleting the RawHBA SR. %s" % (str(e)))

            # Releasing the fibre channel storage array 
            if self.DESTROY_VOLUME:
                self.netAppFiler.release()
            else:
                xenrt.TEC().logverbose("Not destroying volume in tear-down as requested")

class TC18348(LunPerVDI):
    """RawHBA SR Sanity Test"""

    def run(self, arglist=[]):
        # 1. Create the first RawHBA SR.
        #    Creation of RawHBA SR, scans the fibre channel bus as well.
        self.createSR()

        # 2. Verify whether the RawHBA SR has all VDIs.
        #    Expecting 10 VDIs as we have created 10 LUNs by default.
        self.checkSR()
        
        # 3. Remove/Forget the RawHBA.
        #    Delete/Destroy operation for RawHBA SR is unsupported.
        self.deleteSR()

class TC18349(LunPerVDI):
    """Verify whether RawHBA SR skips LUNs used by LVHDoHBA"""

    def run(self, arglist=[]):

        # Allow Borehamwood enabled host to create lvmoHBA SR.
        self.enableLVMBasedStorage()

        # Create a lvmoHBA SR on the host using the available static LUN.
        fcLun = xenrt.HBALun(self.hosts)
        fcSR = xenrt.lib.xenserver.FCStorageRepository(self.hosts[0], "LVHDoHBA")
        fcSR.create(fcLun)
        self.hosts[0].addSR(fcSR)

        # Create RawHBA SR.
        self.createSR()
        self.checkSR()

        vdiList = self.sr.listVDIs()

        # Check whether LVHDoHBA SR created above is excluded from the list of LUN/VDIs.
        for vdi in vdiList:
            vdiNameLabel = self.hosts[0].genParamGet("vdi", vdi, "name-label")
            if vdiNameLabel:
                if (vdiNameLabel == fcLun.getID()):
                    raise xenrt.XRTFailure("LUN/VDI SR includes LUNs used by LVHDoHBA.")
            else:
                raise xenrt.XRTFailure("The name-label of vdi uuid: %s is reported to be empty." % vdi)

        # Delete the lvmoHBA SR created.
        self.hosts[0].destroySR(fcSR.uuid)

        # Prepare the Borehamwood enabled host for subsequent tests by disallowing to create LVM based SR.
        self.disableLVMBasedStorage()

class TC18354(LunPerVDI):
    """Verify the behaviour when a LUN/VDI is forgotten from RawHBA SR"""

    def run(self, arglist=[]):

        # Create SR & verify ther 
        self.createSR()
        self.checkSR()

        vdiList = self.sr.listVDIs()
        lenVdiList = len(vdiList)

        # Delete the all the VDIs from the list including the static luns, if any.
        for vdiuuid in vdiList:
            self.hosts[0].getCLIInstance().execute("vdi-forget","uuid=%s" % (vdiuuid))

        vdiList = self.sr.listVDIs()

        # Check the number of VDIs in the SR.
        if (len(vdiList) == 0):
            xenrt.TEC().logverbose("All the VDIs are removed from the rawHBA SR as expected.")
        else:
            xenrt.TEC().logverbose("The VDIs seen under the raWHBA SR are: %s" % str(vdiList))
            raise xenrt.XRTFailure("LUN/VDIs are seen under the rawHBA SR even after forgetting all VDIs.")

        # Scan the SR to verify further.
        self.sr.scan()

        vdiList = self.sr.listVDIs()
        # Verify the SR is non-empty and has the same number of VDIs as before.
        if (len(vdiList) != lenVdiList):
            xenrt.TEC().logverbose("Expecting %d Found %d." % (lenVdiList, len(vdiList)))
            raise xenrt.XRTFailure("The SR reported incorrect number of VDIs for the test.")

class TC18355(LunPerVDI):
    """Verify the behaviour while adding/deleting a LUN from the storage array."""

    def run(self, arglist=[]):
        # 1. Create the first RawHBA SR.
        self.createSR()

        # 2. Expecting 10 VDIs as we have created 10 LUNs by default.
        self.checkSR()
        
        # 3. Remove/Forget the RawHBA.
        self.deleteSR()

        # 4. Check what happens to the associated LUNs in the array after SR deletion.
        self.checkLunsIntegrity()

        # 5. Create RawHBA SR again.
        #    Expecting the original 10 VDIs again in step (2).
        self.createSR()
        self.checkSR()
        
        # 6. Add 5 more luns in storage array
        addedLuns = self.netAppFiler.provisionLuns(5, 25, self._createInitiators())
        xenrt.TEC().logverbose("Added %d luns: %s" % (len(addedLuns), str(addedLuns)))

        # 7. Scan the fibre channel bus to update the newly created luns in step(6).
        self.sr.scan()

        # 8. Before checking the SR, update internal variables to reflect the new LUNs added.
        self.updateExtraLuns(addedLuns, self._VdiUpdateMode.Add)

        # 9. Check whether the number of VDIs are updated to 15.
        self.checkSR()

        # 10. Reduce the internal lun variables hoping step (11) succeeds.
        self.updateExtraLuns(addedLuns, self._VdiUpdateMode.Remove)

        # 11. Now delete these 5 luns from the array under the volume vName.
        #    Alternatively, one can use self.destroyLun(vName)
        map(lambda lunId: self.netAppFiler.destroyLun(lunId), addedLuns)

        # 12. Scan the fibre channel bus to refelct the deleted luns.
        self.sr.scan()

        # 13. Check whether the number of VDIs are updated back to 10.
        self.checkSR()

        # Either 14a or 14b
        # 14a. Delete all the LUNs created for this test.
        #      And check whether the SR reports empty VDIs
        #self.destroyLun(None, True) # force=True deletion, if luns are mapped.
        #self.checkSR() # This fails as the VDIs are in stale sate, if we delete the luns.
        
        # 14b. Remove/Forget SR and associated luns to verify the empty SR creation scenario.
        self.deleteSR()
        self.checkLunsIntegrity()
        self.netAppFiler.destroyLuns() # force=True deletion, if luns are mapped.

        # 15. Create an empty RawHBA SR (with no mapped LUNs at all)
        #     And check SR has any VDIs. Expecting 0 VDIs.
        self.createSR()
        self.checkSR()

        # 16. Remove/Forget the empty RawHBA SR. Delete/Destroy SR is unsupported.
        self.deleteSR()
        self.checkLunsIntegrity()

class TC18369(LunPerVDI):
    """Verify whether creation of second RawHBA SR is possible in the system."""

    def run(self, arglist=[]):
        # 1. Create the first RawHBA SR
        self.createSR()

        if self.sruuid:
            xenrt.TEC().logverbose("The first rawHBA SR is created on host %s." % self.hosts[0])
        else:
            raise xenrt.XRTFailure("The first rawHBA SR is not created on host %s." % self.hosts[0])

        # If the first RawHBA SR is succeded, try creating the second one.
        try:
            self.createSR()
        except Exception, e:
            # XRTFailure: CLI command sr-create failed: 
            # The SR operation cannot be performed because a device underlying the SR is in use by the host.
            if re.search("performed because a device underlying the SR", str(e)):
                xenrt.TEC().logverbose("The second rawHBA SR is not created on host %s as expected." % self.hosts[0])
            else:
                raise xenrt.XRTFailure("The host %s allows to create more than one RawHBA SR: %s" % (self.hosts[0], str(e)))

class TC18357(LunPerVDI):
    """Verify the system updates VDI size when the associated LUN size is changed in the storage array"""

    def run(self, arglist=[]):

        # 1. Create the first RawHBA SR
        self.createSR()

        # 2. Expecting 10 VDIs as we have created 10 LUNs by default.
        self.checkSR()

        # 3. Select a VDI to be resized, resize and verify the result.
        if (len(self.vdiuuids) > 0):
            # Get the last LUN/VDI from the list.
            getVDI = self.vdiuuids[len(self.vdiuuids)-1]

            # Retrieve the virtual size, physical size and name-label (SCSID) of the VDI.
            virtualSizeBefore = int(self.hosts[0].genParamGet("vdi", getVDI, "virtual-size"))
            vdiNameLabel = self.hosts[0].genParamGet("vdi", getVDI, "name-label")

            xenrt.TEC().logverbose("Before resize virtual size: %d for VDI: %s" %
                                        (virtualSizeBefore, getVDI))

            # When there are multipaths for the same LUN, 
            # all the devices of the LUN should report same disk size.
            deviceSizeBefore = []
            devices = self.hosts[0].execdom0("ls -ltr /dev/disk/by-scsid/%s/sd*; exit 0" % (vdiNameLabel))
            devices = devices.splitlines()
            for device in devices:
                tmp = device.split("/")[-1]
                deviceSizeBefore.append(int(self.hosts[0].execdom0("cat /sys/block/%s/size; exit 0" % (tmp))))

            xenrt.TEC().logverbose("The devices size for LUN %s before resize are %s." %
                                    (vdiNameLabel, deviceSizeBefore))

            # deviceSizeBefore list should have all identical elements.
            if (len(set(deviceSizeBefore)) != 1):
                raise xenrt.XRTFailure("The devices size for LUN: %s before resize are having varying sizes." %
                                        vdiNameLabel)

            xenrt.TEC().logverbose("The devices size for LUN %s has same size %d before resize." %
                                    (vdiNameLabel, list(set(deviceSizeBefore))[0]))

            # Deduce the NetApp serial number of the associated LUN of the VDI.
            targetLun = next(lun for lun in self.netAppFiler.getLuns() if lun.getID() == vdiNameLabel)

            xenrt.TEC().logverbose("Serial number of the LUN to be resized %s." % targetLun.getNetAppSerialNumber())

            lunSize = targetLun.size()
            
            if (lunSize > 0):
                # Choose a higher size.
                newSizeBytes = lunSize + (10 * xenrt.GIGA) # adding 10 GB
                xenrt.TEC().logverbose("Resizing the LUN with serial number: %s from %d to %d" %
                                            (targetLun.getNetAppSerialNumber(), virtualSizeBefore, newSizeBytes))

                # Resize the LUN now.
                targetLun.resize(newSizeBytes/xenrt.MEGA, False)

                # Rescan the fibre channel bus to refelct the resized lun.
                self.sr.scan()

                # Retrieve the virtual size, physical size of the VDI to compare.
                virtualSizeAfter = int(self.hosts[0].genParamGet("vdi", getVDI, "virtual-size"))

                xenrt.TEC().logverbose("After resize virtual size: %d for VDI: %s" %
                                            (virtualSizeAfter, getVDI))

                deviceSizeAfter = []
                devices = self.hosts[0].execdom0("ls -ltr /dev/disk/by-scsid/%s/sd*; exit 0" % (vdiNameLabel))
                devices = devices.splitlines()
                for device in devices:
                    tmp = device.split("/")[-1]
                    deviceSizeAfter.append(int(self.hosts[0].execdom0("cat /sys/block/%s/size; exit 0" % (tmp))))

                xenrt.TEC().logverbose("The devices size for LUN %s after resize are %s." %
                                        (vdiNameLabel, deviceSizeAfter))

                # deviceSizeBefore list should have all identical elements.
                if (len(set(deviceSizeAfter)) != 1):
                    raise xenrt.XRTFailure("The devices size for LUN: %s after resize are having varying sizes." %
                                            vdiNameLabel)

                xenrt.TEC().logverbose("The devices size for LUN %s has same size %d after resize." %
                                        (vdiNameLabel, list(set(deviceSizeAfter))[0]))

                expectedDeviceSize = (list(set(deviceSizeBefore))[0] * 512) + (10 * xenrt.GIGA)
                foundDeviceSize = list(set(deviceSizeAfter))[0] * 512
                if (expectedDeviceSize != foundDeviceSize):
                    xenrt.TEC().logverbose("Expected: %d Found %d" % (expectedDeviceSize, foundDeviceSize))
                    raise xenrt.XRTFailure("The devices size are not updated after the LUN resize in storage.")
                else:
                    xenrt.TEC().logverbose("The devices size for the given lun %s reflects the resized LUN." % (vdiNameLabel))

                if ((virtualSizeBefore +(10 * xenrt.GIGA)) != virtualSizeAfter):
                    xenrt.TEC().logverbose("Expected: %d Found %d" %
                                                ((virtualSizeBefore +(10 * xenrt.GIGA)) , virtualSizeAfter))
                    raise xenrt.XRTFailure("LUN/VDI virtual size for the VDI %s is not updated after the LUN resize in storage." % (getVDI))
                else:
                    xenrt.TEC().logverbose("The virtual size of the VDI reflects the resized LUN.")
            else:
                raise xenrt.XRTFailure("A corresponding LUN for the LUN/VDI %s is not found in the array." % getVDI) 
        else:
            raise xenrt.XRTFailure("No VDIs under the rawHBA SR to be tested.") 

#class TC18350(LunPerVDI):Verify life cycle operations of a Windows VM with RawHBA SR.
#class TC18351(LunPerVDI):Verify life cycle operations of a Linux VM with RawHBA SR.
class VMLifeCycle(LunPerVDI):
    """Verify life cycle operations of a VM with RawHBA SR."""

    def run(self, arglist=[]):

        # 1. Create the first RawHBA SR
        self.createSR()

        # 2. Check the the number of VDIs created against the number of LUNs.
        self.checkSR()

        # 3. Form a list with a root disk and required extra disks.
        # Windows without PV drivers will allow only 4 disks.
        # First disk will be root and the rest will be extra disks.
        diskList = [self.vdiuuids[0],self.vdiuuids[1], self.vdiuuids[2]]

        # 4. Create the Windows gusest by attaching the root disk and required extra disks.
        xenrt.TEC().logverbose("Creating a Windows guest by attaching root disk and required extra disks.")
        self.guest = self.hosts[0].createBasicGuest(distro=self.DISTRO, rawHBAVDIs=diskList)
        self.getLogsFrom(self.guest)

        # 5. Perform guest lifecycle operations.
        xenrt.TEC().logverbose("Performing lifecycle operations on VM...")
        self.guest.shutdown()
        self.guest.start()
        self.guest.reboot()
        self.guest.suspend()
        self.guest.resume()

        # Delete the VM.
        self.guest.shutdown()
        try:
            self.guest.lifecycleOperation("vm-destroy", force=True)
        except Exception, e:
            if re.search("The uuid you supplied was invalid", str(e)):
                xenrt.TEC().warning("Expected error while deleting the LUN/VDI VM. %s" % (str(e)))
            else:
                raise

class TCBwdEnvironment(LunPerVDI):
    """Prepares a minimal Borehamwood environment"""

    def run(self, arglist=[]):

        # Create the RawHBA SR on the master.
        self.createSR()

        # Create the pool
        self.pool = xenrt.lib.xenserver.poolFactory(self.hosts[0].productVersion)(self.hosts[0])
        self.pool.master = self.hosts[0]

        # Add all remaining hosts to the pool.
        for host in self.hosts[1:]:
            # The host joining the pool cannot contain any shared storage.
            for sr in host.minimalList("sr-list", args="content-type=iso type=iso"):
                host.forgetSR(sr)
            self.pool.addHost(host)
        self.pool.setPoolParam("name-label", "rawHBAPool")
        self.pool.check()

        # Set the pool default SR to be the RawHBA SR.
        self.pool.setPoolParam("default-SR", self.sruuid)

        xenrt.TEC().logverbose("There are %s VDIs [%s] in the test" % (len(self.vdiuuids), self.vdiuuids))

        if len(self.vdiuuids) == 0:
            raise xenrt.XRTFailure("The test failed to populate required LUN/VDIs.")

        # Form a list with a root disk and one or more required extra disks.
        diskList1 = [self.vdiuuids[0],self.vdiuuids[1], self.vdiuuids[2]]
        diskList2 = [self.vdiuuids[3],self.vdiuuids[4], self.vdiuuids[5]]
        diskList3 = [self.vdiuuids[6],self.vdiuuids[7], self.vdiuuids[8]]

        # Create one windows & linux guests.
        #self.guests = xenrt.pfarm([xenrt.PTask(self.hosts[0].createBasicGuest, distro=self.WINDISTRO ,rawHBAVDIs=diskList1),
        #                           xenrt.PTask(self.hosts[0].createBasicGuest, distro=self.LINDISTRO ,rawHBAVDIs=diskList2)])

        # Installing serially.
        self.guests.append(self.hosts[0].createBasicGuest(distro=self.WINDISTRO ,rawHBAVDIs=diskList1))
        self.guests.append(self.hosts[0].createBasicGuest(distro=self.LINDISTRO ,rawHBAVDIs=diskList2))
        self.guests.append(self.hosts[0].createBasicGuest(distro=self.DISTRO ,rawHBAVDIs=diskList3))

class TC18352(TCBwdEnvironment):
    """Verify life cycle operations of a VM with RawHBA SR in a pool of servers."""

    def run(self, arglist=[]):

        # Prepare the basic borehamwood environment.
        TCBwdEnvironment.run(self, arglist=[])

        # Verify that VM can go through the life cycle operations.
        xenrt.TEC().logverbose("VM Life Cycle Operations...")
        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()

        # Remove all the slave from the pool.
        for host in self.hosts[1:]:
            self.pool.eject(host)
 
        # Verify that VMs can start on the master and not on the slave.
        self.guests[0].start()

        # Verify the ejected host cannot see the RawHBA SR.
        for host in self.hosts[1:]:
            srs = host.getSRs()
            if self.sruuid in srs:
                raise xenrt.XRTFailure("Ejected slave can still see RawHBA SR.")

class TC18358(TCBwdEnvironment):
    """Verify the migration of a VM with RawHBA SR in a pool of servers."""

    def migrationOfRawHBAGuest(self, host):
        for guest in self.guests:
            self.getLogsFrom(guest)
            guest.migrateVM(host=host, live="true")
            guest.check()
            xenrt.sleep(60)

    def run(self, arglist=[]):
    
        # Prepare the basic borehamwood environment.
        TCBwdEnvironment.run(self, arglist=[])

        # Verify that VM can be migrated to slave.
        xenrt.TEC().logverbose("VM Migration to slave ...")
        self.migrationOfRawHBAGuest(self.hosts[1])

        # Verify that VM can be migrated back to master.
        xenrt.TEC().logverbose("VM Migration back to master ...")
        self.migrationOfRawHBAGuest(self.hosts[0])

class TC18365(LunPerVDI):
    """Verify a minimum of 256 LUNs can be mapped as part of the RawHBA SR feature."""

    def run(self, arglist=[]):
        addedLuns = self.netAppFiler.provisionLuns(246, 1, self._createInitiators()) # + 10 default created in prepare()
        map(lambda host : host.scanScsiBus(), self.hosts)

        timeNow = xenrt.util.timenow()
        self.createSR()
        xenrt.TEC().logverbose("Time taken to create rawHBA SR on host with 256 LUNs mapped: %s seconds." % 
                                    (xenrt.util.timenow() - timeNow))

        self.updateExtraLuns(addedLuns, self._VdiUpdateMode.Add)

        self.checkSR()

        timeNow = xenrt.util.timenow()
        self.sr.scan()
        xenrt.TEC().logverbose("Time taken to scan the host with 256 LUNs mapped: %s seconds." % 
                                    (xenrt.util.timenow() - timeNow))

        # Now verify time to boot system with 256 LUNs mapped.
        timeNow = xenrt.util.timenow()
        self.hosts[0].reboot()
        xenrt.TEC().logverbose("Time taken to reboot the host with 256 LUNs mapped: %s seconds." % 
                                    (xenrt.util.timenow() - timeNow))

        self.checkSR()

        timeNow = xenrt.util.timenow()
        self.deleteSR()
        xenrt.TEC().logverbose("Time taken to destroy the host with 256 LUNs mapped: %s seconds." % 
                                    (xenrt.util.timenow() - timeNow))

class TC18382(LunPerVDI):
    """Verify the migration of a VDI from a traditional SR type to RawHBA SR."""

    def run(self, arglist=[]):

        # 1. create a VM on the default local SR
        guest = self.hosts[0].createBasicGuest(distro=self.LINDISTRO)
        self.getLogsFrom(guest)
        self.guests.append(guest)

        # 2. Get the VDI of the  installed VM. It has one VDI attached.
        traditionalVMVDIUUID = self.guests[0].getAttachedVDIs()[0]

        xenrt.TEC().logverbose("VDI uuid of the guest %s is %s" % (self.guests[0], traditionalVMVDIUUID))

        if not traditionalVMVDIUUID:
            raise xenrt.XRTFailure("Root disk of the guest %s is not found." % self.guests[0])

        # 3. Shutdown the VM. At the moment we have only one VM.
        for guest in self.guests:
            guest.preCloneTailor()
            guest.shutdown()

        # 4. Destroy the VBDs.
        for vbd in self.hosts[0].minimalList("vbd-list", args="vm-uuid=%s type=Disk" % self.guests[0].getUUID()):
            self.hosts[0].getCLIInstance().execute("vbd-destroy","uuid=%s" % (vbd))

        # 5. Create the first RawHBA SR
        self.createSR()

        # 6. Check the the number of VDIs created against the number of LUNs.
        self.checkSR()

        # 7. Copy the VDI of the VM to LUN/VDI using the migration script.
        try:
            self.hosts[0].execdom0("cp %s/remote/migrate_LVHDVDI_RAWVDI.py /opt/xensource/sm" %
                                        (xenrt.TEC().lookup("REMOTE_SCRIPTDIR")))
            self.hosts[0].execdom0("cd /opt/xensource/sm && python migrate_LVHDVDI_RAWVDI.py %s %s" %
                                                (self.vdiuuids[0], traditionalVMVDIUUID), timeout=900)
        except Exception, e:
            raise xenrt.XRTFailure("The rawHBA migration script failed with an error: %s" % str(e))

        # 8. Clone the VM (only meta-data is cloned as the disk is dettached.)
        newName = "new-cloned-VM-%s" % self.LINDISTRO
        args = []
        args.append("vm=\"%s\"" % (self.guests[0].getUUID()))
        args.append("new-name-label=\"%s\"" % (newName))
        clonedVMUUID = self.hosts[0].getCLIInstance().execute("vm-clone", string.join(args), ignoreerrors=True)

        # 9. Attach the copied LUN/VDI to the cloned VM.
        args = []
        args.append("vm-uuid=\"%s\"" % (clonedVMUUID))
        args.append("vdi-uuid=\"%s\"" % (self.vdiuuids[0]))
        args.append("device=0")
        args.append("bootable=true")
        args.append("mode=RW")
        args.append("type=Disk")
        self.hosts[0].getCLIInstance().execute("vbd-create", string.join(args), ignoreerrors=True)

        # 10. Check whether VM comes up.
        self.hosts[0].getCLIInstance().execute("vm-start","uuid=%s" % (clonedVMUUID))

        # 11. Attach more disks to the created VM.
        for guest in self.guests: # there is only one VM.
            for newVDI in self.vdiuuids[1:]: # attach all the remaining VDIs.
                args = []
                # Default to lowest available device number.
                allowed = guest.getHost().genParamGet("vm", guest.getUUID(), "allowed-VBD-devices")
                userdevice = str(min([int(x) for x in allowed.split("; ")]))
                args.append("device=%s" % (userdevice))
                args.append("vdi-uuid=\"%s\"" % (newVDI))
                args.append("vm-uuid=\"%s\"" % (guest.getUUID()))
                args.append("mode=RW")
                args.append("type=Disk")
                newGuestVBD = guest.getHost().getCLIInstance().execute("vbd-create", string.join(args), ignoreerrors=True)

class TC20568(LunPerVDI):
    """Verify a minimum of 256 Hardware HBA SR can be created in XenServer environment"""

    def run(self, arglist=[]):
        addedLuns = self.netAppFiler.provisionLuns(65, 1, self._createInitiators()) # + 10 default created in prepare()
        map(lambda host : host.scanScsiBus(), self.hosts)

        # 2. Create lvmoHBA SRs on the master.
        counter = 0
        timeNow = xenrt.util.timenow()
        self.lvmohbaSRObject = [] # list of lvmoHBA SR objects
        for lun in self.netAppFiler.getLuns():
            fcName = ("lvmoHBASR%d" % counter)
            fcSR = xenrt.lib.xenserver.FCStorageRepository(self.hosts[0], fcName, thin_prov=(self.tcsku=="thin"))
            self.lvmohbaSRObject.append(fcSR)
            fcSR.create(lun)
            counter = counter + 1

        xenrt.TEC().logverbose("Time taken to create %d lvmoHBA SR on master %s is %s seconds." % 
                                (len(self.lvmohbaSRObject), self.hosts[0], (xenrt.util.timenow() - timeNow)))

    def postRun(self, arglist=[]):

        # Destroy the lvmoHBA SR on the pool.
        timeNow = xenrt.util.timenow()
        for hbaSR in self.lvmohbaSRObject:
            self.hosts[0].destroySR(hbaSR.uuid)
        xenrt.TEC().logverbose("Time taken to destroy the lvmoHBA SR on %d hosts pool: %s seconds." % 
                                    (len(self.lvmohbaSRObject), (xenrt.util.timenow() - timeNow)))

        # Releasing the fibre channel storage array 
        if self.DESTROY_VOLUME:
            self.netAppFiler.release()
        else:
            xenrt.TEC().logverbose("Not destroying volume in tear-down as requested")

class TC18370(LunPerVDI):
    """Verify sharing of same LUN/VDI between multiple VMs is possible"""

    def run(self, arglist=[]):
        
        # 1. Create Raw LUN SR on the host
        step("Preparing the LUN SR")
        self.createSR()

        # 2. Check the number of created VDIs against the number of LUNs.
        self.checkSR()

        # 3. Prepare the VMs
        step("Preparing the first VM")
        diskList1 = [self.vdiuuids[0]]
        guestVM1 = self.hosts[0].createBasicGuest(distro=self.LINDISTRO, rawHBAVDIs=diskList1)
        self.guests.append(guestVM1)

        step("Preparing the second VM")
        diskList2 = [self.vdiuuids[3]]
        guestVM2 = self.hosts[0].createBasicGuest(distro=self.LINDISTRO, rawHBAVDIs=diskList2)
        self.guests.append(guestVM2)

        # 4. Attempt to set up a RO VDI share between the two VMs
        step("Attempt to attach a VDI to the first VM as a RO drive")
        guestVM1.createDisk(userdevice="5", vdiuuid=self.vdiuuids[6], mode="RO")
        try:
            step("Attempt to attach the same VDI to the second VM as a RO drive")
            guestVM2.createDisk(userdevice="5", vdiuuid=self.vdiuuids[6], mode="RO")
            log("The VDI was attached successfully")
        except Exception,e:
            raise xenrt.XRTFailure("It was not possible to share a rawhba VDI between two guest VMs on the same physical machine: %s" %e)

class TC18371(LunPerVDI):
    """Verify that LUN/VDI SR should not be listed as the potential HA statefile SR."""

    CONFIG_KEY = "VDI_GENERATE_CONFIG"

    def run(self, arglist=[]):

        # 1. Check the rawhba SR driver features to see whether it's a potential HA statefile.     
        step("Checking the rawhba driver features.") 
        rawHBAcapabilities = self.hosts[0].minimalList(command="sm-list", params="features", args="type=rawhba")

        if re.search(self.CONFIG_KEY, str(rawHBAcapabilities)):
            raise xenrt.XRTFailure("The \"%s\" is present in the capabilities section of the drivers for the relevant SR - it will be listed \
as a potential HA statefile SR. The capabilities that are listed are: %s" % (self.CONFIG_KEY, rawHBAcapabilities))
        else:
            log("The \"%s\" is NOT present in the capabilities section of the drivers for the relevant SR - it will not be listed as a \
potential HA statefile SR - which is the expected behaviour. The capabilities that are listed are: %s" % (self.CONFIG_KEY, rawHBAcapabilities))

class TC18372(LunPerVDI):
    """Verify that HA statefile VDI should not be listed as the available LUN/VDI"""

    def run(self, arglist=[]):

        self.enableLVMBasedStorage()

        step("Creating a single-host pool")
        self.pool = xenrt.lib.xenserver.poolFactory(self.hosts[0].productVersion)(self.hosts[0])
        self.pool.master = self.hosts[0]

        step("Creating a lvmohba SR")
        lun = xenrt.HBALun(self.hosts)
        hba = xenrt.lib.xenserver.HBAStorageRepository(self.hosts[0], "hbasr")
        hba.create(lun)
        self.pool.addSRToPool(hba)
        
        step("Enabling HA on the lvmohba SR")
        self.pool.enableHA()

        step("Checking the uuid of the statefile")
        statefiles = self.hosts[0].minimalList(command="host-list", params="ha-statefiles")
         
        self.disableLVMBasedStorage()

        step("Creating a rawhba SR")
        self.createSR()
        rawhbaVDIs = self.hosts[0].minimalList(command="sr-list", params="VDIs", args="uuid=%s" % self.sruuid)

        step("Ensuring that the HA statefile is not one of the VDIs of the newly created rawhba SR")  
        if re.search(str(hba.uuid), str(rawhbaVDIs)):
            raise xenrt.XRTFailure("HA statefile VDI is listed as one of the available LUN/VDI: %s." % str(hba.uuid))        
        log("HA statefile VDI has not been found on the rawHBA SR. The test succeeded.")

        step("Cleaning up")  
        self.pool.disableHA()
        hba.release()

class TC18373(LunPerVDI):
    """Verify whether DR feature works with LUN/VDI SR"""

    EXPECTED_ERROR = "Disaster recovery not supported on SRs of type rawhba"

    def run(self, arglist=[]):

        # 1. Create Raw LUN SR on the host
        step("Creating a LUN/VDI SR")
        self.createSR()

        # 2. Attempt to enable DR on the default pool
        try:
            step("Attempting to enable DR on the LUN/VDI SR: %s" % self.sruuid)   
            drtask = DRTaskManager().createDRTask(self.hosts[0], type="rawhba") 
        except Exception, e:
            warning("An exception has been caught: %s" % e)     
            if not re.search(self.EXPECTED_ERROR, str(e)):
                raise xenrt.XRTFailure("It is possible to enable DR on the following LUN/VDI SR: %s." % self.sruuid)
            else:            
                xenrt.TEC().logverbose("It is not possible to enable DR on the LUN/VDI SR - expected behaviour")   
        else:
            raise xenrt.XRTFailure("It is possible to enable DR on the following LUN/VDI SR: %s." % self.sruuid) 
        
class TC18374(LunPerVDI):
    """Verify whether the snapshot operation of LUN/VDI is permitted"""

    EXPECTED_ERROR = "The SR backend does not support the operation"

    def run(self, arglist=[]):

        # 1. Create Raw LUN SR on the host
        step("Creating a rawhba SR on the host")
        self.createSR()

        # 2. Check the number of created VDIs against the number of LUNs.
        self.checkSR()

        # 3. Create a guest VM.
        step("Creating a guest VM whose VDIs will reside on the rawhba SR")
        diskList = [self.vdiuuids[0],self.vdiuuids[1], self.vdiuuids[2]]
        guest = self.hosts[0].createBasicGuest(distro=self.LINDISTRO, rawHBAVDIs=diskList)
        self.guests.append(guest)

        # 4. Attempt to snapshot the newly created VM
        try:
            step("Attempting to snapshot the newly created VM")
            guest.snapshot()
        except Exception, e:
            warning("An exception has been caught: %s" % e)
            if not re.search(self.EXPECTED_ERROR, str(e)):
                raise xenrt.XRTFailure("It is possible to snapshot a VM residing on a LUN/VDI that is associated with the following host %s." % self.hosts[0])
            else:
                log("It was not possible to snapshot a VM whose VDIs reside on a rawhba SR") 
        else:
            raise xenrt.XRTFailure("It is possible to snapshot a VM residing on a LUN/VDI that is associated with the following host %s." % self.hosts[0])  

class TC18375(LunPerVDI):
    """Verify whether checkpoint (disk and memory snapshots) operation of LUN/VDI is permitted"""

    EXPECTED_ERROR = "The SR backend does not support the operation"

    def run(self, arglist=[]):

        # 1. Create Raw LUN SR on the host
        step("Creating a rawhba SR")
        self.createSR()

        # 2. Check the number of created VDIs against the number of LUNs.
        self.checkSR()

        # 3. Create a guest VM on the rawhba SR.
        step("Creating a guest VM on the rawhba SR.")
        diskList = [self.vdiuuids[0],self.vdiuuids[1], self.vdiuuids[2]]
        guest = self.hosts[0].createBasicGuest(distro=self.LINDISTRO, rawHBAVDIs=diskList)
        self.guests.append(guest)

        # 4. Attempt to checkpoint the newly created VM
        try:
            step("Attempting to checkpoint the newly created VM")
            guest.checkpoint()
        except Exception, e:
            warning("An exception has been caught: %s" % e)
            if not re.search(self.EXPECTED_ERROR, str(e)):
                raise xenrt.XRTFailure("It is possible to checkpoint a VM that resides on a rawhba SR.")
            else:
                xenrt.TEC().logverbose("The checkpoint operation is not permitted on a VM that resides on a rawhba SR.") 
        else:
            raise xenrt.XRTFailure("It is possible to checkpoint a VM that resides on a rawhba SR.")      

class TC18376(LunPerVDI):
    """Verify whether the fast clone (multiple leaf snapshot tree) operation of LUN/VDI is permitted"""

    EXPECTED_ERROR = "The SR backend does not support the operation"
    
    def run(self, arglist=[]):

        # 1. Create Raw LUN SR on the host
        step("Creating a rawhba SR.")
        self.createSR()

        # 2. Check the number of created VDIs against the number of LUNs.
        self.checkSR()

        # 3. Create a guest VM whose VDIs reside on the rawhba SR.
        step("Creating a guest VM on the rawhba SR.")
        diskList = [self.vdiuuids[0],self.vdiuuids[1], self.vdiuuids[2]]
        guest = self.hosts[0].createBasicGuest(distro=self.LINDISTRO, rawHBAVDIs=diskList)
        self.guests.append(guest)

        # 4. Attempt to clone the newly created VM
        try:
            step("Attempting to clone the newly created VM")    
            guest.shutdown()        
            guest.cloneVM()
        except Exception, e:
            warning("An exception has been caught: %s" % e)
            if not re.search(self.EXPECTED_ERROR, str(e)):
                raise xenrt.XRTFailure("It is possible to clone a VM whose VDIs reside on a rawhba SR.")
            else:
                log("It is NOT possible to clone a VM whose VDIs reside on a rawhba SR.") 
        else:
            raise xenrt.XRTFailure("It is possible to clone a VM whose VDIs reside on a rawhba SR.")        

class TC18377(LunPerVDI):
    """Verify whether automated snapshots (VMPR) of LUN/VDI is permitted"""

    DEFAULT_VMPP_TIME = "19700101T00:00:00Z"
    DATE_TO_FORCE_VMPP = "date -s \"20151226 18:59:59\""

    def run(self, arglist=[]):

        self.pool = xenrt.lib.xenserver.poolFactory(self.hosts[0].productVersion)(self.hosts[0])
        self.pool.master = self.hosts[0]
        
        # 1. Create Raw LUN SR on the host
        step("Creating a rawHBA SR")
        self.createSR()

        # 2. Check the number of created VDIs against the number of LUNs.
        self.checkSR()

        # 3. Create a guest by attaching the root disk and two extra disks.
        step("Creating a guest by attaching a root disk and two extra disks.")
        diskList = [self.vdiuuids[0],self.vdiuuids[1], self.vdiuuids[2]]
        guest = self.hosts[0].createBasicGuest(distro=self.LINDISTRO, rawHBAVDIs=diskList)
        self.guests.append(guest)

        # 4. Set up VMPP for the newly created VM
        step("Setting up hourly VMPR for the one existing VM")    
        vmppID = self.pool.createVMPP(name = "vmpp", type = "snapshot", frequency = "hourly")    
        vmppID = vmppID.rstrip('\n')

        # 5. Add the guest VM to the policy
        step("Adding the VM to the VMPP policy")   
        guest.paramSet("protection-policy", vmppID)

        # 6. Set the time to force the vmpp to run in 1 second
        step("Setting fake time to force the vmpp to run in one second")   
        self.hosts[0].execdom0(self.DATE_TO_FORCE_VMPP)

        # 7. wait for the vmpp to run, use a counter to prevent a possible infinite loop
        step("Waiting for the vmpp to run")   
        counter =0
        lastVMPPRunTime = string.join(self.hosts[0].minimalList("vmpp-list", "backup-last-run-time"))

        while(re.search(self.DEFAULT_VMPP_TIME, lastVMPPRunTime)):
            time.sleep(5)
            lastVMPPRunTime = string.join(self.hosts[0].minimalList("vmpp-list", "backup-last-run-time"))
            counter += 1
            if (counter >= 24):
                raise xenrt.XRTFailure("The test timed out while waiting for the VMPP policy to run (timed out after 120 seconds).")

        # 8. Check the snapshots that were created to see if any are a result of the VMPP being run
        step("Checking whether any snapshots were created as a result of the vmpp being run")
        vmSnapshotData = string.join(self.hosts[0].minimalList("vm-list", "is-snapshot-from-vmpp"))
        snapshotList = string.join(self.hosts[0].minimalList("snapshot-list", "is-snapshot-from-vmpp"))

        if(re.search("true", vmSnapshotData) or re.search("vmpp", snapshotList)):
            raise xenrt.XRTFailure("An automated VMPP snapshot was allowed on a VM residing on a LUN/VDI - the test failed. Snapshot list: %s" % snapshotList)

        log("An automated VMPP snapshot was NOT allowed on a VM residing on a LUN/VDI - the test succeeded. Snapshot list: %s" % snapshotList) 

class TC18378(LunPerVDI):
    """Verify whether Storage Xen Motion is possible with LUN/VDI SR"""

    def run(self, arglist=[]):

        # 1. Create the RawHBA SR on the master.
        step("Create a rawhba SR.")
        self.createSR()

        # 2. Create a guest VM on the rawhba SR.
        step("Create a VM whose VDI resides on the rawhba SR.")
        diskList = [self.vdiuuids[0]]
        guest = self.hosts[0].createBasicGuest(distro=self.LINDISTRO, rawHBAVDIs=diskList)
        self.guests.append(guest)

        numVDIsHost2preSMotion = len(self.hosts[1].minimalList("vdi-list", "name-label"))

        # 3. Attempt a Storage XenMotion from host 1 rawhba to host 2 local storage        
        try:
            step("Attempt a Storage XenMotion from host 1 rawhba to host 2 local storage")
            guest.migrateVM(remote_host=self.hosts[1], remote_user="root", remote_passwd="xenroot", live="true")
            raise xenrt.XRTFailure("It was possible to use Storage XenMotion to migrate the VM from a rawHBA to a local SR on a different machine.")
        except Exception, e:
            warning("It was not possible to migrate the VM. The operation failed with the following error message: %s" %e)

        # 4. Ensure that no new VDIs were created on host 2
        step("Compare the number of VDIs pre and post the Stoage XenMotion attempt")
        numVDIsHost2postSMotion = len(self.hosts[1].minimalList("vdi-list", "name-label"))
        if(numVDIsHost2preSMotion < numVDIsHost2postSMotion):
            raise xenrt.XRTFailure("%d new VDIs were created on host 2 even though Storage XenMotion failed" % (numVDIsHost2postSMotion - numVDIsHost2preSMotion))

        # 5. Ensure that the VM was not transferred onto host 2
        step("Ensure that the VM was not transferred onto the second host")
        migratedVMs = self.hosts[1].minimalList("vm-list", "name-label")
        if(re.search(str(guest), migratedVMs)):
            raise xenrt.XRTFailure("It was possible to use Storage XenMotion to migrate the VM from a rawHBA to a local SR on a different machine.")
