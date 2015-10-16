#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases specific to (L)VHD SRs
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, os.path, random, operator
import xenrt, testcases
from xenrt.lazylog import step

class VHDorVDI(object):

    TYPE = None

    def __init__(self, uuid=None, size=None):
        self.uuid = uuid
        self.hidden = False
        self.parent = None
        self.children = []
        self.size = size
        self.name = None
        self.readonly = False

    def __str__(self):
        if self.uuid:
            s = "%s %s" % (self.TYPE, self.uuid)
        else:
            s = "%s (UUID not known yet)" % (self.TYPE)
        if self.hidden:
            s = s + " hidden"
        if self.parent:
            if self.parent.uuid:
                s = s + " parent=%s" % (self.parent.uuid)
            else:
                s = s + " parent=(UUID not known yet)"
        return s

    def dump(self, indent=""):
        rc = indent + str(self) + "\n"
        for c in self.children:
            rc = rc + c.dump(indent+"  ")
        return rc

    def clone(self, uuid=None):
        v = self.__class__(uuid, self.size)
        return v

class VHD(VHDorVDI):
    """Represents a VHD file/volume in the topology structure"""
    TYPE = "VHD"

class VDI(VHDorVDI):
    """Represents a non-hidden VDI in the topology structure"""
    TYPE = "VDI"

#############################################################################
# Superclass with common functionality

class _VHDTestSuperClass(xenrt.TestCase):
    """Parent class for VHD coalesce and garbage collection tests."""

    # This template testcase provides wrappers around VDI operations
    # that maintain a shadow copy of the VDI and VHD relationship
    # structure. Various parts of the test will use the shadow copy
    # to validate the system under test is behaving as expected.

    # The testcase structure is:
    #  1. the prepare method constructs a scenario. The individual testcases
    #     can implement a setup() method to perform per-TC prepare steps.    
    #  2. the test body performs some kind of operation
    #  3. the common test body verifies the system is in the state defined
    #     by the shadow data

    # Additionally the common test will verify that no left over VDIs and
    # VHDs exist.

    # The shadow data is a topology of VDIs and a corresponding
    # topology of VHDs. Note that a VDI topology is as seen by the user, i.e.
    # a clone/snapshot is a child of the original VDI; the VHD topology is
    # as seen by the SM driver, i.e. a clone/snapshot and the original will
    # both be children of a common readonly parent.

    # The final validation checks will first "coalesce" the shadow data.

    MAINHOST = "master"
    TIMEOUT = 10 # Mins
    SRTYPE = None

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        if self.host.pool:
            self.host = self.host.pool.master
        self.master = self.host
        if self.MAINHOST == "slave":
            self.host = self.master.pool.getSlaves()[0]        
        self.cli = self.host.getCLIInstance()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]

        # Make sure all existing coalesce actvity has completed before we start
        self.waitForCoalesce()

        # Record the initial VHDs and VDIs present
        self.prevvdis = self.host.minimalList("vdi-list",
                                              args="sr-uuid=%s" % (self.sr))
        self.prevvhds = self.host.listVHDsInSR(self.sr)

        # We'll build the expected topology in here as we go
        self.expectedVHDTopology = [] # list topmost parent VHD objects
        self.vhdObjectLookup = {} # uuid -> VHD object
        self.expectedVDITopology = [] # list of topmost VDI objects
        self.vdiObjectLookup = {} # uuid -> VDI object

        # Create the initial topology
        self.vdiLookup = {} # name -> uuid
        self.setup()
        self.displayExpected()
        
        # Verify the initial topology
        self.check(True)

    def setup(self):
        """Override this method in the testcases to setup a scenario"""
        pass
    
    def modify(self):
        """Override this method in the testcases to perform an action"""
        raise xenrt.XRTError("Test case transformation function unimplemented")

    def checkVDIs(self, vdis, parent=None):
        """Checks a VDI topology"""
        exists = self.host.minimalList("vdi-list",
                                       args="sr-uuid=%s" % (self.sr))
        for vdi in vdis:
            #name, size, readonly, thin, attached, smconfig, children = vdi
            uuid = vdi.uuid
            name = vdi.name
            #uuid = self.getVDIByName(name)
            if not uuid in exists:
                raise xenrt.XRTFailure("Expected VDI '%s' not found" % (name),
                                       uuid)
            virtsize = long(self.host.genParamGet("vdi", uuid, "virtual-size"))
            if virtsize != vdi.size:
                raise xenrt.XRTFailure("Unexpected VDI size for '%s'" % (name),
                                       "Expected %u, got %u" %
                                       (vdi.size, virtsize))
            ro = self.host.genParamGet("vdi", uuid, "read-only")
            if (ro == "true" and not vdi.readonly) or \
                   (ro == "false" and vdi.readonly):
                raise xenrt.XRTFailure("Unexpected read-only status for '%s'" %
                                       (name),
                                       "Expected %s, got %s" %
                                       (str(vdi.readonly), ro))
            missing = self.host.genParamGet("vdi", uuid, "missing")
            if missing == "true":
                raise xenrt.XRTFailure("VDI '%s' marked as missing" % (name))
            managed = self.host.genParamGet("vdi", uuid, "managed")
            if managed == "false":
                raise xenrt.XRTFailure("VDI '%s' marked as unmanaged" % (name))
            
            if vdi.children:
                self.checkVDIs(vdi.children, uuid)

    def checkVHDs(self, vhds, parent=None):
        """Checks a VHD topology and returns a list of VHD UUIDs"""
        buildlist = []
        for vhd in vhds:
            self.checkVHD(vhd, buildlist)
        return buildlist

    def checkVHD(self, vhd, buildlist=None):
        """Checks a VHD and returns the UUID of the parent VHD and of itself"""
        #name, size, readonly, thin, attached, smconfig, children = vhdtuple
        name = vhd.name

        # Check the children first to get the list of parent VHDs which
        # should all match and be us.
        if vhd.children:
            # If we have children then this can't be a main VHD for a VDI
            if name:
                raise xenrt.XRTError("VHD '%s' shouldn't have any children" %
                                     (name))
            uuid = None
            for c in vhd.children:
                puuid, cuuid = self.checkVHD(c, buildlist)
                if not puuid:
                    raise xenrt.XRTFailure("Child VHD claims not to have a "
                                           "parent",
                                           cuuid)
                if not uuid:
                    uuid = puuid
                elif uuid != puuid:
                    raise xenrt.XRTFailure(\
                        "VHDs expected to have the same parent do not",
                        "%s and %s" % (uuid, puuid))
            if not uuid:
                raise xenrt.XRTError("Did not find our UUID from the kids")
            # Now we know our UUID we can check the VHD exists and look for
            # a parent
            if not self.host.vhdExists(uuid, self.sr):
                raise xenrt.XRTFailure("Parent VHD not found in SR",
                                       uuid)
            parentuuid = self.host.vhdQueryParent(uuid)

            # This non-leaf VHD will have a readonly, unmanaged VDI record
            dummyvdis = self.host.minimalList(\
                "vdi-list",
                args="sr-uuid=%s managed=false read-only=true" % (self.sr))
            if not uuid in dummyvdis:
                raise xenrt.XRTFailure("Non-leaf VHD does not have a "
                                       "read-only, unmanaged VDI record",
                                       uuid)
        else:
            # This is a leaf node which means it is the main VHD for a VDI
            if not name:
                raise xenrt.XRTError("Leaf VHD defined without a name")
            uuid = self.getVDIByName(name)
            parentuuid = self.host.vhdQueryParent(uuid)
            # Check this matches the VDI param
            try:
                p = self.host.genParamGet("vdi",
                                          uuid,
                                          "sm-config",
                                          "vhd-parent")
            except:
                p = None
            if p != parentuuid:
                text = "VHD and VDI disagree about VHD parent"
                text2 = "VDI param says %s, VHD says %s" % (p, parentuuid)
                if xenrt.TEC().lookup("VHD_PARENT_WARN_ONLY",
                                      False,
                                      boolean=True):
                    xenrt.TEC().warning(text + ". " + text2)
                else:
                    raise xenrt.XRTFailure(text, text2)

        # TODO: check on-disk size/allocation

        if buildlist != None:
            buildlist.append(uuid)
        return parentuuid, uuid

    def check(self, initial):
        """Check the VHD and VDI topology"""
        self.checkVDIs(self.expectedVDITopology)
        self.checkVHDs(self.expectedVHDTopology)

    def checkLeftOvers(self):
        """Check for any leaked VDIs or VHDs"""
        extravdis = 0
        extravhds = 0
        vdis = self.host.minimalList("vdi-list",
                                     args="sr-uuid=%s" % (self.sr))
        vhds = self.host.listVHDsInSR(self.sr)

        # We'll allow any VDIs/VHDs present before the test prepare method
        # ran and any that were expected in the outcome.
        okvdis = self.listVDIUUIDs(self.expectedVDITopology)
        okvhds = self.checkVHDs(self.expectedVHDTopology)

        # Non-leaf VHDs have readonly, unmanaged VDI objects, add these
        # to the acceptable list
        for vhd in okvhds:
            if not vhd in okvdis:
                okvdis.append(vhd)

        okvdis.extend(self.prevvdis)
        okvhds.extend(self.prevvhds)

        for vdi in vdis:
            if not vdi in okvdis:
                xenrt.TEC().logverbose("VDI %s exists when we didn't expect it"
                                       % (vdi))
                extravdis = extravdis + 1
                
        for vhd in vhds:
            if not vhd in okvhds:
                xenrt.TEC().logverbose("VHD %s exists when we didn't expect it"
                                       % (vhd))
                extravhds = extravhds + 1

        if extravdis > 0 and extravhds > 0:
            raise xenrt.XRTFailure("One or more VDI+VHDs left over")
        if extravdis > 0:
            raise xenrt.XRTFailure("One or more VDIs left over")
        if extravhds > 0:
            raise xenrt.XRTFailure("One or more VHDs left over")


    def checkMissedCoalesce(self):
        """Sanity check that no hidden VDI has a single hidden child"""
        # (if it did then the child should have been coalesced into the
        # parent)
        # TODO
        pass

    def listVDIUUIDs(self, topology, accumulator=None):
        """Return a list of VDI UUIDs in a topology"""
        if accumulator == None:
            accumulator = []
        for t in topology:
            accumulator.append(t.uuid)
            self.listVDIUUIDs(t.children, accumulator)
        return accumulator

    def getVDIByName(self, name):
        """Return a VDI UUID given the name from the topology definition."""
        if self.vdiLookup.has_key(name):
            return self.vdiLookup[name]
        raise xenrt.XRTError("VDI not defined: '%s'" % (name))

    def createVDI(self, name, size, thin=None, smconfig=None):
        """Create a new VDI"""
        if thin:
            if smconfig:
                smconfig = "%s allocation=thin" % (smconfig)
            else:
                smconfig = "allocation=thin"
        uuid = self.host.createVDI(size,
                                   sruuid=self.sr,
                                   smconfig=smconfig,
                                   name=name)
        xenrt.TEC().comment("Created VDI %s ('%s')" % (uuid, name))
        self.vdiLookup[name] = uuid
        # This will be a single VHD file and a single VDI
        v = VHD(uuid, size)
        v.name = name
        self.expectedVHDTopology.append(v)
        self.vhdObjectLookup[uuid] = v
        v = VDI(uuid, size)
        v.name = name
        self.expectedVDITopology.append(v)
        self.vdiObjectLookup[uuid] = v

    def cloneVDIByName(self, name, newname, origunchanged=False):
        """Clone the named VDI and give it the new name"""
        # Setting origunchanged=True means that the original VDI has not
        # been written to since the last time it was cloned, i.e. the
        # new clone can be another child of the current parent of the 
        # original
        if self.vdiLookup.has_key(newname):
            raise xenrt.XRTError("Duplicate VDI name '%s'" % (newname))
        origuuid = self.getVDIByName(name)
        uuid = self.cli.execute("vdi-clone", "uuid=%s" % (origuuid)).strip()
        self.cli.execute("vdi-param-set",
                         "uuid=%s name-label=%s" % (uuid, newname))
        try:
            pattern = self.host.genParamGet("vdi",
                                            uuid,
                                            "other-config",
                                            "xenrt-pattern")
            pattlen = self.host.genParamGet("vdi",
                                            uuid,
                                            "other-config",
                                            "xenrt-pattlen")
            self.host.genParamSet("vdi",
                                  uuid,
                                  "other-config",
                                  pattern,
                                  "xenrt-pattern")
            self.host.genParamSet("vdi",
                                  uuid,
                                  "other-config",
                                  pattlen,
                                  "xenrt-pattlen")
        except:
            pass
        xenrt.TEC().comment("Cloned VDI %s ('%s') from %s ('%s')" %
                            (uuid, newname, origuuid, name))
        self.vdiLookup[newname] = uuid
        if origunchanged:
            # Find the original VHD file ("vorig") in the expected topology
            # and clone it:
            #  1. Create a new VHD for the clone "vclone"
            #  2. Make the parent of vclone be the same as the parent of vorig
            #  3. Update the child list in the parent of vorig
            vorig = self.vhdObjectLookup[origuuid]
            vclone = vorig.clone(uuid)
            self.vhdObjectLookup[uuid] = vclone
            vclone.parent = vorig.parent
            vclone.name = newname
            vclone.parent.children.append(vclone)
        else:
            # Find the original VHD file ("vorig") in the expected topology
            # and clone it:
            #  1. Create a new hidden VHD "vparent"
            #  2. Create a new VHD for the clone "vclone"
            #  3. Make the parent of vparent the same as the parent of vorig
            #  4. Make the parent of vorig and vclone be vparent
            #  5. Update the child lists in all related VHDs
            vorig = self.vhdObjectLookup[origuuid]
            vclone = vorig.clone(uuid)
            self.vhdObjectLookup[uuid] = vclone
            vparent = vorig.clone(None)
            vparent.hidden = True
            vparent.parent = vorig.parent

            if vorig.parent:
                vorig.parent.children.remove(vorig)
                vorig.parent.children.append(vparent)
            vclone.parent = vparent
            vclone.name = newname
            vorig.parent = vparent
            vparent.children.append(vclone)
            vparent.children.append(vorig)

            if vorig in self.expectedVHDTopology:
                self.expectedVHDTopology.remove(vorig)
                self.expectedVHDTopology.append(vparent)

        # And the VDI object
        vdiorig = self.vdiObjectLookup[origuuid]
        vdiclone = vdiorig.clone(uuid)
        vdiclone.parent = vdiorig
        vdiclone.name = newname
        vdiorig.children.append(vdiclone)
        self.vdiObjectLookup[uuid] = vdiclone

    def destroyVDIByName(self, name):
        """Destroy the named VDI"""
        uuid = self.getVDIByName(name)
        self.cli.execute("vdi-destroy", "uuid=%s" % (uuid))
        del self.vdiLookup[name]

        # Remove VHD object but do not coalesce
        vhd = self.vhdObjectLookup[uuid]
        del self.vhdObjectLookup[uuid]
        if vhd.parent:
            vhd.parent.children.remove(vhd)
        else:
            self.expectedVHDTopology.remove(vhd)

        # Remove VDI object
        vdi = self.vdiObjectLookup[uuid]
        del self.vdiObjectLookup[uuid]
        for c in vdi.children:
            c.parent = None
            self.expectedVDITopology.append(c)
        if vdi.parent:
            vdi.parent.children.remove(vdi)
        else:
            self.expectedVDITopology.remove(vdi)

    def calculateCoalescingVHD(self, vhd):
        if vhd.parent and vhd.hidden and len(vhd.parent.children) == 1:
            # Can coalesce and remove this VHD
            vhd.parent.children = vhd.children
            for c in vhd.children:
                c.parent = vhd.parent
            # Now continue processing but skipping this now deleted VHD
            vhd = vhd.parent
        for c in vhd.children:
            self.calculateCoalescingVHD(c)

    def calculateCoalescing(self):
        """Update the expected VHD topology after coalescing."""
        # For each VHD in each tree we'll check if its parent has only the one
        # child and if so "coalesce" this one into the parent and fix up the
        # topology.
        for vhd in self.expectedVHDTopology:
            self.calculateCoalescingVHD(vhd)

    def writeRandomDataToVDIByName(self, name):
        """Use dom0 block attach to write some random data to a VDI"""
        uuid = self.getVDIByName(name)
        size = long(self.host.genParamGet("vdi", uuid, "virtual-size"))
        cmd = ""
        for i in range(8):
            cmd = cmd + \
                  "dd if=/dev/random of=/dev/${DEVICE} bs=4096 count=1 seek=%u\n" \
                  % (random.randint(0, size/4096))
        self.vdicommand(uuid, cmd)
        try:
            self.host.genParamRemove("vdi", uuid, "other-config", "xenrt-pattern")
            self.host.genParamRemove("vdi", uuid, "other-config", "xenrt-pattlen")
        except:
            pass

    def writePatternToVDIByName(self, name, patternid=0):
        """Write a deterministic pattern to a named VDI"""
        uuid = self.getVDIByName(name)
        size = long(self.host.genParamGet("vdi", uuid, "virtual-size"))
        cmd = "%s/remote/patterns.py /dev/${DEVICE} %d write 1 %u" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size, patternid)
        self.vdicommand(uuid, cmd)
        self.host.genParamSet("vdi",
                              uuid,
                              "other-config",
                              "%u" % (patternid),
                              "xenrt-pattern")
        self.host.genParamSet("vdi",
                              uuid,
                              "other-config",
                              "%u" % (size),
                              "xenrt-pattlen")

    def checkPatternOnVDIByName(self, name, patternid=0):
        """Check a deterministic pattern on a named VDI"""
        uuid = self.getVDIByName(name)
        size = long(self.host.genParamGet("vdi", uuid, "virtual-size"))
        cmd = "%s/remote/patterns.py /dev/${DEVICE} %d read 1 %u" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size, patternid)
        self.vdicommand(uuid, cmd)

    def vdicommand(self, vdiuuid, command):
        sftp = self.host.sftpClient()
        sd = self.host.hostTempDir()
        t = xenrt.TempDirectory()
        
        s = "%s/cmd.sh" % (sd)
        filename = "%s/cmd.sh" % (t.path())
        
        file(filename, "w").write(command)
        sftp.copyTo("%s/cmd.sh" % (t.path()), s)
        self.host.execdom0("chmod +x %s" % (s))
        data = self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" %  
                                  (vdiuuid, s))
        self.host.execdom0("rm -rf %s" % (sd))
        t.remove()
        return data

    def displayDebug(self):
        """Log a debug dump of the SR's VHD structure"""
        self.host.vhdSRDisplayDebug(self.sr)

    def displayExpected(self):
        """Log a debug dump of the expected VDI and VHD topologies"""
        xenrt.TEC().logverbose("Expected VDI topology:")
        for vdi in self.expectedVDITopology:
            xenrt.TEC().logverbose("\n" + vdi.dump())
        xenrt.TEC().logverbose("End VDI topology dump.")
        xenrt.TEC().logverbose("Expected VHD topology:")
        for vhd in self.expectedVHDTopology:
            xenrt.TEC().logverbose("\n" + vhd.dump())
        xenrt.TEC().logverbose("End VHD topology dump.")

    def waitForCoalesce(self):
        start = xenrt.timenow()
        self.host.waitForCoalesce(self.sr, self.TIMEOUT * 60)
        end = xenrt.timenow()
        xenrt.TEC().logverbose("Coalesce took approximately %u minutes" %
                               (int((end-start)/60)))

    def run(self, arglist):

        self.displayDebug()

        # Perform the testcase specific function
        if self.runSubcase("modify", (), "Run", "Test") != xenrt.RESULT_PASS:
            return

        # Let the coalescing happen
        self.waitForCoalesce()
        
        xenrt.TEC().logverbose("Expected topology before coalescing")
        self.displayExpected()
        self.calculateCoalescing()
        xenrt.TEC().logverbose("Expected topology after coalescing")
        self.displayExpected()
        self.displayDebug()

        # Check the resultant topology is what we expected
        if self.runSubcase("check", (False), "Check", "Outcome") != \
               xenrt.RESULT_PASS:
            return

        # Check no left over VDIs and VHDs exist
        if self.runSubcase("checkLeftOvers", (), "Check", "Leaks") != \
               xenrt.RESULT_PASS:
            return

        # Sanity check that no hidden VDI has a single hidden child
        if self.runSubcase("checkMissedCoalesce", (), "Check", "Missed") != \
               xenrt.RESULT_PASS:
            return

    def postRun(self):

        if self.sr:
            # Return the state to what it was before we started by performing
            # a vdi-destroy on all the VDIs that exist that were not here
            # before
            for vdi in self.host.minimalList("vdi-list",
                                             args="sr-uuid=%s" % (self.sr)):
                if not vdi in self.prevvdis:
                    vbds = self.host.minimalList("vbd-list",
                                                 args="vdi-uuid=%s" % (vdi))
                    for vbd in vbds:
                        try:
                            self.cli.execute("vbd-unplug", "uuid=%s" % (vbd))
                        except:
                            pass
                        try:
                            self.cli.execute("vbd-destroy", "uuid=%s" % (vbd))
                        except:
                            pass
                    try:
                        self.cli.execute("vdi-destroy", "uuid=%s" % (vdi))
                    except:
                        pass
            try:
                self.cli.execute("sr-scan", "uuid=%s" % (self.sr))
            except:
                pass

#############################################################################
# Basic garbage collection tests

class _TCDestroySimple(_VHDTestSuperClass):
    """Destroy a single non-cloned VDI."""

    def setup(self):
        # Create an initial VDI
        self.createVDI("vdi1", 4294967296)

    def modify(self):
        # Destroy the VDI
        self.destroyVDIByName("vdi1")

class _TCSuspendImageGC(_VHDTestSuperClass):
    """A VDI used as a suspend image should be garbage collected after use"""

    def modify(self):
        # Create a VM
        guest = self.host.createGenericLinuxGuest()        
        self.uninstallOnCleanup(guest)

        # Ensure the suspend SR is set for this SR
        prevsuspendsr = self.host.getHostParam("suspend-image-sr-uuid")
        if prevsuspendsr != self.sr:
            self.host.setHostParam("suspend-image-sr-uuid", self.sr)

        # If this is a Boston+ host we also need to set the suspend-SR on the VM
        # pre-Boston this will fail so do it inside a try/except block
        try:
            guest.paramSet("suspend-SR-uuid", self.sr)
        except:
            pass
            
        try:
            # Suspend the VM
            guest.suspend()

            # Locate the suspend VDI
            vdiuuid = guest.paramGet("suspend-VDI-uuid")
            if vdiuuid == "<not in database>":
                raise xenrt.XRTError("Suspend VDI not found")
            sruuid = self.host.genParamGet("vdi", vdiuuid, "sr-uuid")
            if sruuid != self.sr:
                raise xenrt.XRTError("Suspend VDI not on the SR we wanted",
                                     "VDI %s on SR %s" % (vdiuuid, sruuid))
            if not self.host.vhdExists(vdiuuid, self.sr):
                raise xenrt.XRTFailure("Suspend VDI's VHD not found",
                                       vdiuuid)
            
            # Resume the VM
            guest.resume()

            # Verify the suspend VDI has gone
            time.sleep(60)
            try:
                self.host.genParamGet("vdi", vdiuuid, "sr-uuid")
            except:
                pass
            else:
                raise xenrt.XRTFailure("Suspend VDI still exists after resume",
                                       vdiuuid)
            if self.host.vhdExists(vdiuuid, self.sr):
                raise xenrt.XRTFailure(\
                    "Suspend VDI's VHD still exists after resume", vdiuuid)

            # Uninstall the VM
            guest.shutdown()
            guest.uninstall()
            
        finally:
            # Put the suspend SR back if we changed it
            if prevsuspendsr != self.sr:
                self.host.setHostParam("suspend-image-sr-uuid", prevsuspendsr)


#############################################################################
# Basic coalescing functional tests

class _TCCoalesceDeletedCloneSimple(_VHDTestSuperClass):
    """VHD coalescing removing intermediate unused VHD after deletion of one of two clones of the same original."""

    def setup(self):

        # Create an initial VDI
        self.createVDI("orig", 4294967296)

    def modify(self):

        # Write some data to the original VDI
        self.writeRandomDataToVDIByName("orig")

        # Clone the original VDI
        self.cloneVDIByName("orig", "clone1")

        # Write some data to the original VDI
        self.writeRandomDataToVDIByName("orig")

        # Clone the VDI again
        self.cloneVDIByName("orig", "clone2")

        # Write some more data to the original VDI
        self.writeRandomDataToVDIByName("orig")

        self.displayExpected()
        
        # Destroy the first cloned VDI
        self.destroyVDIByName("clone1")

#############################################################################
# Coalescing data integrity tests


# Create a pattern on the original

# Perform a clone

# Modify the original

#

class _TCCoalesceDeletedCloneData(_VHDTestSuperClass):
    """Data integrity of a series of clones after removing the first clone"""

    SIZE = 1073741824
    CLONES_TO_MAKE = [0, 1, 2, 3]
    CLONES_TO_REMOVE = [0]

    def setup(self):

        # Create an initial VDI
        self.createVDI("orig", self.SIZE)

    def modify(self):

        # Make 4 clones with data changes to the original between each
        for i in self.CLONES_TO_MAKE:
            self.writePatternToVDIByName("orig",  i)
            self.cloneVDIByName("orig", "clone%u" % (i))

        # Write a pattern to the original
        self.writePatternToVDIByName("orig")

        # Remove some clones
        for i in self.CLONES_TO_REMOVE:
            self.destroyVDIByName("clone%u" % (i))

        # Let the coalescing to happen
        self.waitForCoalesce()

        # Check the patterns on the VDIs
        for i in self.CLONES_TO_MAKE:
            if not i in self.CLONES_TO_REMOVE:
                self.checkPatternOnVDIByName("clone%u" % (i),  i)
        self.checkPatternOnVDIByName("orig")

#############################################################################
# Coalescing when children have been resized

#############################################################################
# Deep coalesce

#############################################################################
# Multiple parallel coalesce opportunities

#############################################################################
# Plugged VDIs using snapshot instead of clone

#############################################################################
# Reparenting with many children
class _TCCoalesceDeletedCloneManyKids(_VHDTestSuperClass):
    """Reparenting with many children when coalescing"""

    N = 1000
    TIMEOUT = 60 # Mins

    def setup(self):

        # Create an initial VDI
        self.createVDI("origA", 8388608)

    def modify(self):

        # Write some data to the original VDI
        self.writeRandomDataToVDIByName("origA")

        # Clone the original VDI
        self.cloneVDIByName("origA", "cloneB")

        # Write some data to the original VDI
        self.writeRandomDataToVDIByName("origA")

        # Clone the VDI again 1000 times
        for i in range(self.N):
            self.cloneVDIByName("origA", "clone%04u" % (i), origunchanged=i)

        self.displayExpected()

        # Destroy the first cloned VDI
        self.destroyVDIByName("cloneB")

#############################################################################
# Should not be able to clone hidden (parent) VDIs
class _TCHiddenVDINoClone(_VHDTestSuperClass):
    """Clone of a hidden VDI is not allowed"""

    def setup(self):
        
        # Create an initial VDI
        self.createVDI("origA", 8388608)

        # Write some data to the original VDI
        self.writeRandomDataToVDIByName("origA")

        # Clone the VDI
        self.cloneVDIByName("origA", "cloneB")

        self.displayDebug()

        # Determine the hidden parent
        uuid = self.getVDIByName("origA")
        parent = self.host.genParamGet("vdi", uuid, "sm-config", "vhd-parent")
        if self.host.genParamGet("vdi", parent, "managed") != "false":
            raise xenrt.XRTError("Hidden parent VDI not marked managed=false")
        self.parent = parent

    def run(self, arglist):

        self.displayDebug()

        # Attempt to clone the hidden parent
        clonevdi = None
        try:
            try:
                clonevdi = self.cli.execute("vdi-clone",
                                            "uuid=%s" % (self.parent)).strip()
            except xenrt.XRTFailure, e:
                if re.search(r"Failed to clone VDI.*hidden VDI", e.data) or \
                       re.search(r"This operation cannot be performed because the system does not manage this VDI", e.data):
                    # This is good
                    xenrt.TEC().logverbose("Clone failed as expected")
                else:
                    raise e
        finally:
            if clonevdi:
                try:
                    self.cli.execute("vdi-destroy", "uuid=%s" % (clonevdi))
                except:
                    pass

#############################################################################
# Scenarios                                                                 #
#############################################################################

#############################################################################
# Local VHDoEXT on a single host

class TC8553(_TCDestroySimple):
    """Destroy a single non-cloned VHDoEXT VDI."""
    SRTYPE = "ext"

class TC8554(_TCSuspendImageGC):
    """A VHDoEXT VDI used as a suspend image should be garbage collected after use"""
    SRTYPE = "ext"

class TC8555(_TCCoalesceDeletedCloneSimple):
    """VHDoEXT VHD coalescing removing intermediate unused VHD after deletion of one of two clones of the same original."""
    SRTYPE = "ext"

class TC8558(_TCCoalesceDeletedCloneData):
    """Data integrity of a series of VHDoEXT clones after removing the first clone"""
    SRTYPE = "ext"

class TC8762(_TCHiddenVDINoClone):
    """Clone of a hidden VHDoEXT VDI is not allowed"""
    SRTYPE = "ext"

#############################################################################
# Local VHDoEXT on a slave in a pool

class TC8579(_TCDestroySimple):
    """Destroy a single non-cloned VHDoEXT VDI on slave local SR."""
    SRTYPE = "ext"
    MAINHOST = "slave"

class TC8590(_TCSuspendImageGC):
    """A VHDoEXT VDI on a slave local SR used as a suspend image should be garbage collected after use"""
    SRTYPE = "ext"
    MAINHOST = "slave"

class TC8591(_TCCoalesceDeletedCloneSimple):
    """VHDoEXT VHD coalescing removing intermediate unused VHD after deletion of one of two clones of the same original on a slave local SR."""
    SRTYPE = "ext"
    MAINHOST = "slave"

class TC8592(_TCCoalesceDeletedCloneData):
    """Data integrity of a series of VHDoEXT clones on a slave local SR after removing the first clone"""
    SRTYPE = "ext"
    MAINHOST = "slave"

#############################################################################
# Shared NFS in a pool of two

class TC8557(_TCDestroySimple):
    """Destroy a single non-cloned NFS VDI."""
    SRTYPE = "nfs"

class TC8584(_TCSuspendImageGC):
    """A NFS VDI used as a suspend image should be garbage collected after use"""
    SRTYPE = "nfs"

class TC8585(_TCCoalesceDeletedCloneSimple):
    """NFS VHD coalescing removing intermediate unused VHD after deletion of one of two clones of the same original."""
    SRTYPE = "nfs"

class TC8586(_TCCoalesceDeletedCloneData):
    """Data integrity of a series of NFS clones after removing the first clone"""
    SRTYPE = "nfs"

#############################################################################
# Local LVM on a single host

class TC8577(_TCDestroySimple):
    """Destroy a single non-cloned LVM VDI."""
    SRTYPE = "lvm"

class TC8581(_TCSuspendImageGC):
    """A LVM VDI used as a suspend image should be garbage collected after use"""
    SRTYPE = "lvm"

class TC8582(_TCCoalesceDeletedCloneSimple):
    """LVM VHD coalescing removing intermediate unused VHD after deletion of one of two clones of the same original."""
    SRTYPE = "lvm"

class TC8583(_TCCoalesceDeletedCloneData):
    """Data integrity of a series of LVM clones after removing the first clone"""
    SRTYPE = "lvm"

class TC8646(_TCCoalesceDeletedCloneManyKids):
    """Reparenting with many children when coalescing a LVM SR"""
    SRTYPE = "lvm"

class TC8763(_TCHiddenVDINoClone):
    """Clone of a hidden LVHD VDI is not allowed"""
    SRTYPE = "lvm"
    
#############################################################################
# Local LVM on a slave in a pool

class TC8580(_TCDestroySimple):
    """Destroy a single non-cloned LVM VDI on a slave local SR."""
    SRTYPE = "lvm"
    MAINHOST = "slave"

class TC8593(_TCSuspendImageGC):
    """A LVM VDI on a slave local SR used as a suspend image should be garbage collected after use"""
    SRTYPE = "lvm"
    MAINHOST = "slave"

class TC8594(_TCCoalesceDeletedCloneSimple):
    """LVM VHD coalescing removing intermediate unused VHD after deletion of one of two clones of the same original on a slave local SR."""
    SRTYPE = "lvm"
    MAINHOST = "slave"

class TC8595(_TCCoalesceDeletedCloneData):
    """Data integrity of a series of LVM clones on a slave local SR after removing the first clone"""
    SRTYPE = "lvm"
    MAINHOST = "slave"

class TC8647(_TCCoalesceDeletedCloneManyKids):
    """Reparenting with many children when coalescing a LVM SR on a slave"""
    SRTYPE = "lvm"
    MAINHOST = "slave"

#############################################################################
# Shared LVMoISCSI in a pool of two

class TC8578(_TCDestroySimple):
    """Destroy a single non-cloned LVMoISCSI VDI."""
    SRTYPE = "lvmoiscsi"

class TC8587(_TCSuspendImageGC):
    """A LVMoISCSI VDI used as a suspend image should be garbage collected after use"""
    SRTYPE = "lvmoiscsi"

class TC8588(_TCCoalesceDeletedCloneSimple):
    """LVMoISCSI VHD coalescing removing intermediate unused VHD after deletion of one of two clones of the same original."""
    SRTYPE = "lvmoiscsi"

class TC8589(_TCCoalesceDeletedCloneData):
    """Data integrity of a series of LVMoISCSI clones after removing the first clone"""
    SRTYPE = "lvmoiscsi"

#############################################################################
# Some pool tests should involve block attach to multiple hosts, e.g. original
# VDI attached to master and a clone attached to slave

#############################################################################
#############################################################################
#############################################################################
#############################################################################
# VDI create matrix

class _TCVDICreate(xenrt.TestCase):
    SMCONFIG = None
    SRTYPE = "lvm"
    ALLOC = "thick"
    MAINHOST = "master"
    DOUPGRADE = None
    TRUELEGACY = False
    VIRTSIZE = 67108864

    # Expected behaviour on initial create
    CREATETYPE = "VHD"
    CREATEPROV = None # match the SR allocation mode

    # Expected behaviour for snapshot VDIs
    SNAPTYPE = "VHD"
    SNAPPROV = "thin"
    SNAPPROVATTACHED = "thick"

    # Expected behaviour for cloned VDIs
    CLONETYPE = "VHD"
    CLONEPROV = None

    # Expected behaviour for parent hidden VDI
    PARENTTYPE = "VHD"
    PARENTPROV = "thin"

    # Expected behaviour for the main VDI after any clone/snapshot
    AFTERTYPE = "VHD"
    AFTERPROV = None

    # Things to try with expected outcomes (e.g. = "pass" or "fail"
    TRYSNAPSHOT = None
    TRYCLONE = None

    ATTACHSNAPSHOT = False

    EXTRASUBCASES = []

    def prepare(self, arglist):
        self.lun = None
        self.tempsr = None
        self.vdi = None

        self.host = self.getDefaultHost()
        if self.host.pool:
            self.host = self.host.pool.master
        self.master = self.host
        if self.MAINHOST == "slave":
            self.host = self.master.pool.getSlaves()[0]
        self.cli = self.host.getCLIInstance()
        if self.DOUPGRADE != None and not self.TRUELEGACY:
            # Need to hack a legacy mode SR in.
            if not self.SRTYPE == "lvmoiscsi":
                raise xenrt.XRTError("Need to use lvmoiscsi SR for this TC")
            # Hack the SM to use a different name for the MGT volume
            self.host.execdom0("sed -e's/MDVOLUME_NAME = \"MGT\"/MDVOLUME_NAME = \"XenRTMGT\"/' -i /opt/xensource/sm/LVHDSR.py")
            if self.host is not self.master:
                self.master.execdom0("sed -e's/MDVOLUME_NAME = \"MGT\"/MDVOLUME_NAME = \"XenRTMGT\"/' -i /opt/xensource/sm/LVHDSR.py")
            try:
                # Create a LVMoISCSI SR on a temporary LUN
                self.lun = xenrt.ISCSITemporaryLun(250)
                self.tempsr = xenrt.lib.xenserver.ISCSIStorageRepository(\
                    self.host, "LegacyLVM")
                self.tempsr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True)
                # Forget and reintroduce the SR putting restoring the sm name
                self.tempsr.forget()
            finally:
                self.host.execdom0("sed -e's/MDVOLUME_NAME = \"XenRTMGT\"/MDVOLUME_NAME = \"MGT\"/' -i /opt/xensource/sm/LVHDSR.py")
                if self.host is not self.master:
                    self.master.execdom0("sed -e's/MDVOLUME_NAME = \"XenRTMGT\"/MDVOLUME_NAME = \"MGT\"/' -i /opt/xensource/sm/LVHDSR.py")
            self.tempsr.introduce()
            # Check the SR is showing as legacy
            try:
                v = self.tempsr.paramGet("sm-config", "use_vhd")
            except:
                pass
            else:
                raise xenrt.XRTError("sm-config:use_vhd set on "
                                     "introduced legacy SR")
            self.sr = self.tempsr.uuid
        else:
            srs = self.host.getSRs(type=self.SRTYPE)
            if not srs:
                raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
            self.sr = srs[0]

            if not self.TRUELEGACY:
                # Check SR allocation mode
                a = self.host.genParamGet("sr", self.sr, "sm-config", "allocation")
                if a != self.ALLOC:
                    raise xenrt.XRTError("SR does not have the correct allocation mode")
        self.vdi = None
        self.vbd = None
        self.snapvdi = None
        self.snapvbd = None
        self.clonevdi = None
        self.clonevbd = None
        self.opdone = False

    def vdicommand(self, vdiuuid, command):
        sftp = self.host.sftpClient()
        sd = self.host.hostTempDir()
        t = xenrt.TempDirectory()

        s = "%s/cmd.sh" % (sd)
        filename = "%s/cmd.sh" % (t.path())

        file(filename, "w").write(command)
        sftp.copyTo("%s/cmd.sh" % (t.path()), s)
        self.host.execdom0("chmod +x %s" % (s))
        data = self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" %
                                  (vdiuuid, s))
        self.host.execdom0("rm -rf %s" % (sd))
        t.remove()
        return data

    def doCreate(self):
        try:
            self.vdi = self.host.createVDI(self.VIRTSIZE,
                                           sruuid=self.sr,
                                           smconfig=self.SMCONFIG)
        except xenrt.XRTFailure, e:
            if self.CREATETYPE == "FAIL":
                if re.search(r"Cannot create VHD type disk in legacy mode",
                             e.data):
                    # This is good
                    xenrt.TEC().logverbose("VDI create failed as expected")
                else:
                    raise e
            else:
                raise e
        else:
            if self.CREATETYPE == "FAIL":
                raise xenrt.XRTFailure("Was able to create a VDI when it "
                                       "was expected to fail")

    def doSnapshot(self):
        secondaryexception = None
        if not self.vbd:
            args = []
            args.append("vdi-uuid=%s" % (self.vdi))
            args.append("vm-uuid=%s" % (self.host.getMyDomain0UUID()))
            args.append("type=Disk")
            args.append("device=4")
            self.vbd = self.cli.execute("vbd-create",
                                        string.join(args)).strip()
        self.cli.execute("vbd-plug", "uuid=%s" % (self.vbd))
        try:
            try:
                self.snapvdi = self.cli.execute("vdi-snapshot",
                                                "uuid=%s" % (self.vdi)).strip()
            finally:
                try:
                    self.cli.execute("vbd-unplug", "uuid=%s" % (self.vbd))
                except Exception, e:
                    secondaryexception = e
        except xenrt.XRTFailure, e:
            if self.TRYSNAPSHOT == "fail":
                if re.search(r"Not_implemented_in_backend", e.data) or \
                        re.search(r"snapshot or clone not permitted", e.data) or \
                        re.search(r"SR_REQUIRES_UPGRADE", e.data) or \
                        re.search(r"The operation cannot be performed until the SR has been upgraded", e.data) or \
                        re.search(r"function which is not implemented", e.data):
                    # This is good
                    xenrt.TEC().logverbose("Snapshot failed as expected")
                else:
                    raise e
            else:
                raise e
        else:
            if self.TRYSNAPSHOT == "fail":
                raise xenrt.XRTFailure("Snapshot succeeded when it should have failed")
        if secondaryexception:
            raise secondaryexception
        if self.TRYSNAPSHOT == "pass":
            self.opdone = True

    def doClone(self):
        try:
            self.clonevdi = self.cli.execute("vdi-clone",
                                             "uuid=%s" % (self.vdi)).strip()
        except xenrt.XRTFailure, e:
            if self.TRYCLONE == "fail":
                if re.search(r"NEED TO KNOW THE ERROR", e.data):
                    # This is good
                    xenrt.TEC().logverbose("Clone failed as expected")
                else:
                    raise e
            else:
                raise e
        else:
            if self.TRYCLONE == "fail":
                raise xenrt.XRTFailure("Clone succeeded when it should have failed")
        if self.TRYCLONE == "pass" or self.TRYCLONE == "slow":
            self.opdone = True

    def doUpgrade(self):
        self.host.execdom0("/opt/xensource/bin/xe-lvm-upgrade %s" %(self.sr))
        time.sleep(15)
        try:
            v = self.host.genParamGet("sr", self.sr, "sm-config", "use_vhd")
        except:
            raise xenrt.XRTFailure("sm-config:use_vhd not set on "
                                   "introduced SR")
        if v != "true":
            raise xenrt.XRTFailure("sm-config:use_vhd=%s on "
                                   "introduced SR" % (v))

    def doCheck(self, id):
        prov = self.ALLOC
        if id == "create":
            if self.opdone:
                if self.AFTERTYPE:
                    exptype = self.AFTERTYPE
                else:
                    exptype = self.CREATETYPE
                if self.AFTERPROV:
                    prov = self.AFTERPROV
                elif self.CREATEPROV:
                    prov = self.CREATEPROV
            else:
                exptype = self.CREATETYPE
                if self.CREATEPROV:
                    prov = self.CREATEPROV
            uuid = self.vdi
        elif id == "snapshot":
            exptype = self.SNAPTYPE
            if self.SNAPPROV:
                prov = self.SNAPPROV
            uuid = self.snapvdi
        elif id == "clone":
            exptype = self.CLONETYPE
            if self.CLONEPROV:
                prov = self.CLONEPROV
            uuid = self.clonevdi
        elif id == "parent":
            exptype = self.PARENTTYPE
            if self.PARENTPROV:
                prov = self.PARENTPROV
            uuid = self.host.genParamGet("vdi", self.vdi, "sm-config", "vhd-parent")
            if not uuid:
                raise xenrt.XRTError("Could not determine parent VHD UUID")
        self._doCheck(uuid, exptype, prov)

    def _doCheck(self, uuid, exptype, prov):
        # Check virtual size
        s = self.host.genParamGet("vdi", uuid, "virtual-size")
        if str(self.VIRTSIZE) != s:
            raise xenrt.XRTError("VDI virtual-size is not as expected",
                                 "Wanted %u, got %s" %
                                 (self.VIRTSIZE, s))

        # Find physical size and allocation
        if self.SRTYPE in ["ext", "nfs"]:
            path = "/var/run/sr-mount/%s/%s.vhd" % (self.sr, uuid)
            if self.host.execdom0("test -e %s" % (path), retval="code") != 0:
                raise xenrt.XRTFailure("VDI missing", uuid)
            foundtype = "VHD"
            foundsize = int(self.host.execdom0("stat -c %s " + path).strip())
        elif self.SRTYPE in ["lvm", "lvmoiscsi", "lvmohba"]:
            vpath = "VG_XenStorage-%s/VHD-%s" % (self.sr, uuid)
            lpath = "VG_XenStorage-%s/LV-%s" % (self.sr, uuid)
            if self.host.execRawStorageCommand(self.sr, "lvdisplay %s" % (vpath), retval="code") == 0:
                foundtype = "VHD"
                foundsize = int(self.host.execRawStorageCommand(self.sr, "lvdisplay -c %s 2> /dev/null" % (vpath)).split(":")[6]) * 512
            elif self.host.execRawStorageCommand(self.sr, "lvdisplay %s" % (lpath), retval="code") == 0:
                foundtype = "LV"
                foundsize = int(self.host.execRawStorageCommand(self.sr, "lvdisplay -c %s 2> /dev/null" % (lpath)).split(":")[6]) * 512
            else:
                raise xenrt.XRTFailure("VDI missing", uuid)
        else:
            raise xenrt.XRTError("VDI type/size check unimplemented for %s" %
                                 (self.SRTYPE))

        # Check provisioning and type
        if exptype and foundtype != exptype:
            raise xenrt.XRTFailure("VDI was %s but we expected %s" %
                                   (foundtype, exptype),
                                   uuid)
        if foundtype == "LV":
            # raw volume should be the same as the virtual size
            if foundsize != self.VIRTSIZE:
                raise xenrt.XRTError("VDI physical size is not as expected",
                                     "Wanted %u, got %u" %
                                     (self.VIRTSIZE, foundsize))
        else:
            if prov == "thick":
                # volume should be larger than the virtual size (to
                # allow for the VHD metadata
                if not foundsize > self.VIRTSIZE:
                    raise xenrt.XRTError("VDI physical size is not as expected",
                                         "Wanted %u, got %u" %
                                         (self.VIRTSIZE, foundsize))
            else:
                # volume size should be smaller than the virtual size
                if not foundsize < self.VIRTSIZE:
                    raise xenrt.XRTError("VDI physical size is not as expected",
                                         "Wanted %u, got %u" %
                                         (self.VIRTSIZE, foundsize))

    def doAttDet(self, clone):
        if clone:
            uuid = self.clonevdi
        else: 
            uuid = self.vdi
        patternid = 0
        size = long(self.host.genParamGet("vdi", uuid, "virtual-size"))
        cmd = "%s/remote/patterns.py /dev/${DEVICE} %d write 1 %u" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size, patternid)
        self.vdicommand(uuid, cmd)
        cmd = "%s/remote/patterns.py /dev/${DEVICE} %d read 1 %u" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size, patternid)
        self.vdicommand(uuid, cmd)

    def doSnapAtt(self):
        secondaryexception = None
        if not self.snapvbd:
            args = []
            args.append("vdi-uuid=%s" % (self.snapvdi))
            args.append("vm-uuid=%s" % (self.host.getMyDomain0UUID()))
            args.append("type=Disk")
            args.append("device=5")
            self.snapvbd = self.cli.execute("vbd-create",
                                            string.join(args)).strip()
        self.cli.execute("vbd-plug", "uuid=%s" % (self.snapvbd))
        try:
            # Check the provisioning
            exptype = self.SNAPTYPE
            prov = self.ALLOC
            if self.SNAPPROVATTACHED:
                prov = self.SNAPPROVATTACHED
            elif self.SNAPPROV:
                prov = self.SNAPPROV
            uuid = self.snapvdi
            self._doCheck(uuid, exptype, prov)
        finally:
            try:
                self.cli.execute("vbd-unplug", "uuid=%s" % (self.snapvbd))
            except Exception, e:
                secondaryexception = e
        if secondaryexception:
            raise secondaryexception

    def run(self, arglist):
        # Perform the VDI create
        if self.runSubcase("doCreate", (), "VDI", "create") != \
               xenrt.RESULT_PASS:
            return
        if self.CREATETYPE == "FAIL":
            return
        if self.runSubcase("doCheck", ("create"), "VDI", "check1") != \
               xenrt.RESULT_PASS:
            return

        # Upgrade the SR if required
        if self.DOUPGRADE:
            if self.runSubcase("doUpgrade", (), "SR", "upgrade") != \
                   xenrt.RESULT_PASS:
                return

        # Test snapshot if required
        if self.TRYSNAPSHOT:
            if self.runSubcase("doSnapshot", (), "VDI", "snapshot") != \
                   xenrt.RESULT_PASS:
                return
        if self.TRYSNAPSHOT == "pass":
            time.sleep(15)
            if self.runSubcase("doCheck", ("snapshot"), "SnapVDI", "check1") != \
                   xenrt.RESULT_PASS:
                return

        # Test clone if required
        if self.TRYCLONE:
            self.doAttDet(False)
            if self.runSubcase("doClone", (), "VDI", "clone") != \
                   xenrt.RESULT_PASS:
                return
        if self.TRYCLONE == "pass" or self.TRYCLONE == "slow":
            time.sleep(15)
            if self.runSubcase("doCheck", ("clone"), "CloneVDI", "check1") != \
                   xenrt.RESULT_PASS:
                return

        # Test the parent VDI if we did snapshot or clone
        if self.TRYSNAPSHOT == "pass" or self.TRYCLONE == "pass":
            if self.runSubcase("doCheck", ("parent"), "ParentVDI", "check1") != \
                   xenrt.RESULT_PASS:
                return

        # Dom0 attach data check
        if self.runSubcase("doAttDet", (False), "VDI", "attachdetach") != \
               xenrt.RESULT_PASS:
            return

        # Check the VDI again
        if self.runSubcase("doCheck", ("create"), "VDI", "check2") != \
               xenrt.RESULT_PASS:
            return

        if self.TRYCLONE == "pass" or self.TRYCLONE == "slow":
            # Dom0 attach data check
            if self.runSubcase("doAttDet", (True), "CloneVDI", "attachdetach") != \
                   xenrt.RESULT_PASS:
                return
            if self.runSubcase("doCheck", ("clone"), "CloneVDI", "check2") != \
                   xenrt.RESULT_PASS:
                return

        if self.ATTACHSNAPSHOT:
            # Dom0 attach data check
            if self.runSubcase("doSnapAtt", (), "SnapshotVDI", "attachdetach") != \
                   xenrt.RESULT_PASS:
                return
            if self.runSubcase("doCheck", ("snapshot"), "SnapshotVDI", "check2") != \
                   xenrt.RESULT_PASS:
                return

        for e in self.EXTRASUBCASES:
            if self.runSubcase(e[0], e[1], e[2], e[3]) != xenrt.RESULT_PASS:
                return

    def postRun(self):
        if self.vbd:
            try:
                self.cli.execute("vbd-unplug", "uuid=%s" % (self.vbd))
            except:
                pass
            try:
                self.cli.execute("vbd-destroy", "uuid=%s" % (self.vbd))
            except:
                pass
        try:
            if self.vdi:
                self.cli.execute("vdi-destroy", "uuid=%s" % (self.vdi))
        except:
            pass
        if self.clonevbd:
            try:
                self.cli.execute("vbd-unplug", "uuid=%s" % (self.clonevbd))
            except:
                pass
            try:
                self.cli.execute("vbd-destroy", "uuid=%s" % (self.clonevbd))
            except:
                pass
        try:
            if self.clonevdi:
                self.cli.execute("vdi-destroy", "uuid=%s" % (self.clonevdi))
        except:
            pass
        if self.snapvbd:
            try:
                self.cli.execute("vbd-unplug", "uuid=%s" % (self.snapvbd))
            except:
                pass
            try:
                self.cli.execute("vbd-destroy", "uuid=%s" % (self.snapvbd))
            except:
                pass
        try:
            if self.snapvdi:
                self.cli.execute("vdi-destroy", "uuid=%s" % (self.snapvdi))
        except:
            pass
        if self.tempsr:
            try:
                self.tempsr.remove()
            except:
                pass
        if self.lun:
            self.lun.release()

# Thick allocation SR creates

class TC8648(_TCVDICreate):
    """VDI create using type=raw on a thick provisioned LVM SR creates a raw VDI"""
    SMCONFIG = "type=raw"
    CREATETYPE = "LV"

class TC8651(_TCVDICreate):
    """VDI create on a thick provisioned LVM SR creates a fully provisioned VHD VDI"""
    CREATETYPE = "VHD"

class TC8662(_TCVDICreate):
    """VDI create using type=vhd on a thick provisioned LVM SR creates a fully provisioned VHD VDI"""
    SMCONFIG = "type=vhd"
    CREATETYPE = "VHD"

# Legacy mode SR creates

class TC8649(_TCVDICreate):
    """VDI create using type=raw on a legacy mode LVM SR creates a raw VDI"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    SMCONFIG = "type=raw"
    DOUPGRADE = False

class TC8650(_TCVDICreate):
    """VDI create on a legacy mode LVM SR creates a raw VDI"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = False

class TC8663(_TCVDICreate):
    """VDI create using type=vhd on a legacy mode LVM SR should fail"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "FAIL"
    SMCONFIG = "type=vhd"
    DOUPGRADE = False

# Create in legacy mode and upgrade

class TC8652(_TCVDICreate):
    """VDI type=raw on a legacy mode SR is raw after upgrading the SR to thick provisioned LVHD"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    SMCONFIG = "type=raw"
    DOUPGRADE = True

class TC8653(_TCVDICreate):
    """VDI on a legacy mode SR is raw after upgrading the SR to thick provisioned LVHD"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = True

# Upgrade

class TC8666(_TCVDICreate):
    """Upgrade LVMoISCSI SR to LVHD with xe-lvm-upgrade"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = True

    EXTRASUBCASES = [("doCheckAlloc", (), "PostUpgrade", "Alloc"),
                     ("doPostUpgradeVDI", (), "PostUpgrade", "VDI")]
    MYALLOC = "thick"
    MYPROV = "thick"
    MYTYPE = "VHD"

    def doCheckAlloc(self):
        # Check the SR allocation mode is correct
        a = self.host.genParamGet("sr", self.sr, "sm-config", "allocation")
        if a != self.MYALLOC:
            raise xenrt.XRTError("SR does not have the correct allocation mode")

    def doPostUpgradeVDI(self):
        # Create a VDI
        vdi = self.host.createVDI(self.VIRTSIZE, sruuid=self.sr)

        # Check it is a fully provisioned VHD
        try:
            self._doCheck(vdi, self.MYTYPE, self.MYPROV)
        finally:
            self.cli.execute("vdi-destroy", "uuid=%s" % (vdi))

class TC8668(TC8666):
    """Upgrade LVM SR installed on previous version to LVHD with xe-lvm-upgrade"""
    DOUPGRADE = True
    TRUELEGACY = True
    SRTYPE = "lvm"

# Negative snapshot/clone

class TC8656(_TCVDICreate):
    """VDI snapshot of a type=raw VDI on a thick provisioned LVHD SR should fail"""
    SMCONFIG = "type=raw"
    CREATETYPE = "LV"
    TRYSNAPSHOT = "fail"

class TC8657(_TCVDICreate):
    """VDI clone of a type=raw VDI on a thick provisioned LVHD SR should fall back to slow copy"""
    SMCONFIG = "type=raw"
    CREATETYPE = "LV"
    CLONETYPE = None
    TRYCLONE = "slow"
    AFTERTYPE = "LV"

class TC8654(_TCVDICreate):
    """VDI snapshot of a VDI on a legacy mode LVM SR should fail"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = False
    TRYSNAPSHOT = "fail"

class TC8655(_TCVDICreate):
    """VDI clone of a VDI on a legacy mode LVM SR should fall back to slow copy"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    CLONETYPE = "LV"
    DOUPGRADE = False
    TRYCLONE = "slow"
    AFTERTYPE = "LV"

# Positive snapshot/clone

class TC8660(_TCVDICreate):
    """VDI snapshot of a VHD VDI on a thick provisioned LVHD SR should succeed"""
    CREATETYPE = "VHD"
    TRYSNAPSHOT = "pass"

class TC9300(_TCVDICreate):
    """VDI snapshot of a VHD VDI on a thick provisioned LVHD SR on a slave should succeed"""
    CREATETYPE = "VHD"
    TRYSNAPSHOT = "pass"
    MAINHOST = "slave"
    
class TC8661(_TCVDICreate):
    """VDI clone of a VHD VDI on a thick provisioned LVHD SR should succeed"""
    CREATETYPE = "VHD"
    TRYCLONE = "pass"

class TC8658(_TCVDICreate):
    """VDI snapshot of a raw VDI (but not type=raw) on a thick provisioned LVHD SR should succeed"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = True
    TRYSNAPSHOT = "pass"
    PARENTTYPE = "LV"

class TC9238(_TCVDICreate):
    """VDI snapshot of a raw VDI (but not type=raw) on a thick provisioned LVHD SR sttached to a VM on a slave should succeed"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = True
    TRYSNAPSHOT = "pass"
    PARENTTYPE = "LV"
    MAINHOST = "slave"

class TC8659(_TCVDICreate):
    """VDI clone of a raw VDI (but not type=raw) on a thick provisioned LVHD SR should succeed"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = True
    TRYCLONE = "pass"
    PARENTTYPE = "LV"

# Snapshot attach inflate/deflate tests

class TC8664(_TCVDICreate):
    """A snapshot VDI on a thick provisioned LVHD SR should be inflated when attached and deflated when not (parent is raw)"""
    SRTYPE = "lvmoiscsi"
    CREATETYPE = "LV"
    DOUPGRADE = True
    TRYSNAPSHOT = "pass"
    ATTACHSNAPSHOT = True
    PARENTTYPE = "LV"

class TC8665(_TCVDICreate):
    """A snapshot VDI on a thick provisioned LVHD SR should be inflated when attached and deflated when not (parent is VHD)"""
    CREATETYPE = "VHD"
    TRYSNAPSHOT = "pass"
    ATTACHSNAPSHOT = True

class _LVHDRTBase(testcases.xenserver.tc._XapiRTBase):
    """Base class for running LVHDRT test cases."""
    TYPE = "lvhd"
    AUTO_UNINSTALL_OLD_VMS = True
    CLEANUP_VDIS_ON_SR_TYPES = ["lvm"]
    CHANGE_PATTERNS_PATH = True
    
    def prepare(self, arglist):
        testcases.xenserver.tc._XapiRTBase.prepare(self, arglist)

class TC8670(_LVHDRTBase):
    """Journalling tests for clone/snapshot/resize."""

    TCID = "8670"
    
class TC8682(_LVHDRTBase):
    """Use DummySR to verify xapi serialisation."""

    TCID = "8682"

    TIMEOUT = 10400

    def extraPrepare(self):
        self.dummy = xenrt.lib.xenserver.DummyStorageRepository(self.host, "dummy")
        self.dummy.create("10GiB")
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.createDisk(sizebytes="10GiB", sruuid=self.dummy.uuid)

    def postRun(self):
        try: self.dummy.forget()
        except: pass

class TC8699(_LVHDRTBase):
    """Make sure hidden vhds' VDIs are not directly usable by clients."""

    TCID = "8699"
    
class TC8700(_LVHDRTBase):
    """Concurrency testing of coalesce."""

    TCID = "8700"

class TC8707(_LVHDRTBase):
    """Space checks."""

    TCID = "8707"

class TC8713(_LVHDRTBase):
    """Make sure SR.lvhd_stop_using_these_vdis is exclusive w.r.t. parallel ops."""

    TCID = "8713"
    TIMEOUT = 3600

    def extraPrepare(self):
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()

class TC8766(_LVHDRTBase):
    """Check the refcounts stored for LVHD SRs under various conditions."""

    TCID = "8766"
    
class TC8775(_LVHDRTBase):
    """Concurent snapshot attach."""

    TCID = "8775"

class _LVHDPerformance(xenrt.TestCase):
    """Test performance of LVHD."""

    MARGIN = 10
    ITERATIONS = 10 
    VDISIZE = 10*1024*1024*1024
 
    IOZONE_HEADERS = [('KB', None), ('reclen', None), 
                      ('write', 0), ('rewrite', 0), 
                      ('read', 1), ('reread', 1), 
                      ('random read', 2), ('random write', 2),
                      ('bkwd read', 3), 
                      ('record rewrite', 4),
                      ('stride read', 5), 
                      ('fwrite', 6), ('frewrite', 6), 
                      ('fread', 7), ('freread', 7)]

    REPORT_BRACKETS = [(5, "Less than 5%"),
                       (10, "5 to 10%"),
                       (15, "10 to 15%"),
                       (20, "20 to 25%"),
                       (30, "20 to 30%"),
                       (50, "30 to 40%"),
                       (None, "More than 50%")]

    def __init__(self, tcid=None, anon=False):
        xenrt.TestCase.__init__(self, tcid=tcid, anon=anon)
        self.tests = []
        self.target = None
        self.path = None
        self.iterations = None

    def parse(self, data):
        """Parse some IOZone output into a dictionary."""
        results = {}
        for line in data.splitlines():
            match = re.match(r"\s*(\d+)" + r"\s*(\d*)" * (len(self.IOZONE_HEADERS)), line)
            if not match: continue
            current = filter(lambda x:x, match.groups())
            headers = filter(lambda (x,y):y in self.tests, self.IOZONE_HEADERS[2:])
            results[(current[0], current[1])] = zip(map(lambda (x,y):x, headers), 
                                                    map(float, current[2:]))
        xenrt.TEC().logverbose("Parsed IOZone output to: %s" % (results))
        return results

    def report(self, a):
        """Report some IOZone results."""
        for k in self.data[a]:
            for l,v in self.data[a][k]:
                xenrt.TEC().value("%s:%s:%s:%s" % ((a,) + k + (l,)), v)
    
    def compare(self, a, b):
        """Compare two IOZone runs."""
        xenrt.TEC().logverbose("Comparing %s to %s." % (a, b))
        self.data["%s/%s" % (a,b)] = {}
        for k in self.data[a]:
            c = map(lambda ((w,x),(y,z)):(w, 100*x/z-100), 
                    zip(self.data[a][k], self.data[b][k]))
            self.data["%s/%s" % (a,b)][k] = c

    def iozonecommand(self, name):
        """Run a single IOZone test on guest."""
        xenrt.TEC().logverbose("Running IOZone test on %s." % 
                               (self.target.getName()))
        tests = reduce(string.join, " ", 
                       ["-i %s" % (x) for x in self.tests])
        data = self.target.execguest("%s %s "   
                                     "-a "      # Auto mode. Required.
                                     "-w "      # Don't delete the target file.
                                     "-n 1g "   # Test files from 1 Gb.
                                     "-g 1g "   # Test files up to 2Gb.
                                     "-r 16m "  # Test only 16Mb records.
                                     "-f %s/iozone_target" % 
                                     (self.iozone, tests, self.path),
                                      timeout=3600)
        self.data[name] = self.parse(data)

    def testrun(self, name):
        """Run a number of IOZone tests and average the results."""
        xenrt.TEC().logverbose("Running %s IOZone iterations on %s" %
                               (self.iterations, self.target.getName()))
        self.data[name] = {}        
        for i in range(self.iterations):
            self.iozonecommand("%s-%s" % (name, i))
            self.target.reboot() 
        for k in self.data["%s-0" % (name)].keys():
            items = [self.data["%s-%s" % (name, x)][k] \
                        for x in range(self.iterations)]
            headers = [ map(lambda (a,b):a, x) for x in items ]
            headers = reduce(lambda x,y:x, headers)
            items = [ map(lambda (a,b):b, x) for x in items ]
            items = map(lambda x:reduce(operator.add, x), zip(*items))
            items = map(lambda x:x/self.iterations, items)
            self.data[name][k] = zip(headers, items)

    def isRaw(self, vdiuuid):
        sruuid = self.host.genParamGet("vdi", vdiuuid, "sr-uuid")
        path = "VG_XenStorage-%s/LV-%s" % (sruuid, vdiuuid)
        try: data = self.host.execRawStorageCommand(sruuid, "lvdisplay -c %s" % (path))
        except: return False
        realsize = int(data.split(":")[6])*512
        virtualsize = int(self.host.genParamGet("vdi", vdiuuid, "virtual-size"))
        return realsize == virtualsize

    def maketarget(self, mountpoint, guest, raw=False):
        """Add a VDI to be tested to a guest."""
        xenrt.TEC().logverbose("Adding test VDI to %s." % (guest.getName()))
        if raw:
            targetuuid = self.host.createVDI(self.VDISIZE, smconfig="type=raw")
            if not self.isRaw(targetuuid):
                raise xenrt.XRTError("VDI is not raw. (%s)" % (targetuuid))
        else:
            targetuuid = self.host.createVDI(self.VDISIZE)
            if self.isRaw(targetuuid):
                raise xenrt.XRTError("VDI is raw. (%s)" % (targetuuid))
        targetdev = guest.createDisk(vdiuuid=targetuuid)
        targetdev = self.host.parseListForOtherParam("vbd-list",    
                                                     "vm-uuid",
                                                      guest.getUUID(),
                                                     "device",
                                                     "userdevice=%s" % (targetdev))
        guest.execguest("mkdir -p %s" % (mountpoint))
        guest.execguest("mkfs.ext2 /dev/%s" % (targetdev))
        guest.execguest("mount /dev/%s %s" % (targetdev, mountpoint))
        guest.execguest("echo /dev/%s %s ext2 defaults 0 0 >> /etc/fstab" %
                        (targetdev, mountpoint))
        
    def checkMargins(self, data):
        failed = False
        for k in self.data[data]:
            for h,v in self.data[data][k]:
                if v < -self.MARGIN:
                    # Bracket the degradation value to help autofiles
                    degdesc = "%1.1f%%" % (v)
                    for br in self.REPORT_BRACKETS:
                        th, desc = br
                        if th == None:
                            degdesc = desc
                            break
                        if v >= -float(th):
                            degdesc = desc
                            break
                    xenrt.TEC().reason("Metric %s has degraded. (%s)" %
                                       (h, degdesc))
                    failed = True
        if failed:
            # Get some debug data requested by Andrei
            try:
                self.host.execdom0("pvdisplay --maps")
            except:
                pass
            raise xenrt.XRTFailure("One or more metrics suffered a performance loss "
                                   "greater than %s%%." % (self.MARGIN))

    def prepare(self, arglist):
        self.data = {}
        self.host = self.getDefaultHost()
        if not self.host.getSRs(type="lvm"):
            raise xenrt.XRTError("No LVHD SR found.")
    
        xenrt.TEC().logverbose("Creating target guest.")        
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        self.guest.execguest("wget %s/iozone.tgz -O /root/iozone.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        self.guest.execguest("tar xvzf /root/iozone.tgz -C /root")
        self.guest.execguest("cd /root/iozone && make linux")
        self.iozone = "/root/iozone/iozone"

class _LVHDChain(_LVHDPerformance):
    """Base class for VHD chain tests."""
   
    # See IOZONE_HEADERS in parent for details of values.
    TEST = None
 
    SNAPSHOTS = 20

    def doSnapshot(self, guest):
        snap = guest.snapshot()
        tfile = guest.execguest("mktemp -p %s" % (self.vhd)).strip()
        guest.execguest("dd if=/dev/urandom of=%s bs=1M count=1" % (tfile))
        return guest

    def prepare(self, arglist):
        _LVHDPerformance.prepare(self, arglist)
        xenrt.TEC().logverbose("Creating reference guest.")
        self.reference = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.reference)
        self.reference.execguest("wget %s/iozone.tgz -O /root/iozone.tgz" %
                                 (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        self.reference.execguest("tar xvzf /root/iozone.tgz -C /root")
        self.reference.execguest("cd /root/iozone && make linux")
        self.raw = "/mnt/raw"
        self.vhd = "/mnt/vhd"

        # CA-35745 We should make the VHD and do the snapshots before creating
        # the raw VDI, otherwise they are too separate on the disk and thus
        # the strange property that I/O to different parts of a disk occurs
        # at different speeds occurs.
        self.maketarget(self.vhd, self.guest)
        xenrt.TEC().logverbose("Creating VHD chain.")
        for i in range(self.SNAPSHOTS):
            self.guest = self.doSnapshot(self.guest)
        self.maketarget(self.raw, self.reference, raw=True)
    
    def run(self, arglist):
        self.tests = [0]
        self.iterations = 1
        self.path = self.raw
        self.target = self.reference
        r = self.runSubcase("testrun", "rawsetup", "LVHD", "rawsetup")
        if not r == xenrt.RESULT_PASS: return
        self.path = self.vhd
        self.target = self.guest
        r = self.runSubcase("testrun", "vhdsetup", "LVHD", "vhdsetup")
        if not r == xenrt.RESULT_PASS: return

        self.tests = self.TEST
        self.iterations = self.ITERATIONS
        self.path = self.raw
        self.target = self.reference
        r = self.runSubcase("testrun", "raw", "LVHD", "raw")
        if not r == xenrt.RESULT_PASS: return
        self.path = self.vhd
        self.target = self.guest
        r = self.runSubcase("testrun", "vhd", "LVHD", "vhd")
        if not r == xenrt.RESULT_PASS: return

        self.compare("vhd", "raw")
        self.report("vhd/raw")
        self.checkMargins("vhd/raw")

class TC8909(_LVHDChain):
    """Random read performance of a VHD chain."""

    TEST = [2]

class TC8908(_LVHDChain):
    """Sequential read performance of a VHD chain."""

    TEST = [1]

class _VHDFirst(_LVHDChain):
    """Subclass that runs the test on the VHD disk first."""

    def run(self, arglist):
        self.tests = [0]
        self.iterations = 1
        self.path = self.vhd
        self.target = self.guest
        r = self.runSubcase("testrun", "vhdsetup", "LVHD", "vhdsetup")
        if not r == xenrt.RESULT_PASS: return
        self.path = self.raw
        self.target = self.reference
        r = self.runSubcase("testrun", "rawsetup", "LVHD", "rawsetup")
        if not r == xenrt.RESULT_PASS: return

        self.tests = self.TEST
        self.iterations = self.ITERATIONS
        self.path = self.vhd
        self.target = self.guest
        r = self.runSubcase("testrun", "vhd", "LVHD", "vhd")
        if not r == xenrt.RESULT_PASS: return
        self.path = self.raw
        self.target = self.reference
        r = self.runSubcase("testrun", "raw", "LVHD", "raw")
        if not r == xenrt.RESULT_PASS: return

        self.compare("vhd", "raw")
        self.report("vhd/raw")
        self.checkMargins("vhd/raw")

class TC11034(_VHDFirst):
    """Random read performance of a VHD chain."""

    TEST = [2]

class TC11033(_VHDFirst):
    """Sequential read performance of a VHD chain."""

    TEST = [1]

class TC8895(_LVHDPerformance):
    """Performance of a LVHD leaf node."""

    def prepare(self, arglist):
        _LVHDPerformance.prepare(self, arglist)
        self.raw = "/mnt/raw"
        self.vhd = "/mnt/vhd"
        self.maketarget(self.raw, self.guest, raw=True)
        self.maketarget(self.vhd, self.guest)

    def run(self, arglist):
        self.tests = [0, 1, 2]
        self.target = self.guest
        self.path = self.raw
        self.iterations = self.ITERATIONS
        self.runSubcase("testrun", "raw", "LVHD", "raw")
        self.path = self.vhd
        self.runSubcase("testrun", "vhd", "LVHD", "vhd")

        self.compare("vhd", "raw")
        self.report("vhd/raw")
        self.checkMargins("vhd/raw")

class TC8910(_LVHDPerformance):
    
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        if not self.host.getSRs(type="lvm"):
            raise xenrt.XRTError("No LVHD SR found.")

        xenrt.TEC().logverbose("Creating target guest.")
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.raw = "/mnt/raw"
        self.vhd = "/mnt/vhd"
        self.maketarget(self.raw, self.guest, raw=True)
        self.maketarget(self.vhd, self.guest)
    
    def run(self, arglist):
        rawtimes = []
        vhdtimes = []

        for i in range(self.ITERATIONS):
            xenrt.TEC().logverbose("Starting iteration %s." % (i))
            start = xenrt.timenow()
            self.guest.execguest(\
                "dd if=/dev/zero of=%s/test bs=1M count=8096" % (self.raw),
                timeout=600)
            end = xenrt.timenow()
            rawtimes.append(end-start)
            start = xenrt.timenow()
            self.guest.execguest(\
                "dd if=/dev/zero of=%s/test bs=1M count=8096" % (self.vhd),
                timeout=1200)
            end = xenrt.timenow()
            vhdtimes.append(end-start)
            
        rawkbs = map(lambda x:8096*1024/x, rawtimes)
        vhdkbs = map(lambda x:8096*1024/x, vhdtimes)
       
        vhdddtime = sum(vhdtimes[1:])/(self.ITERATIONS-1)
        rawddtime = sum(rawtimes[1:])/(self.ITERATIONS-1)
        vhdddkbs = sum(vhdkbs[1:])/(self.ITERATIONS-1)
        rawddkbs = sum(rawkbs[1:])/(self.ITERATIONS-1)
        ratio = 100*vhdddkbs/rawddkbs - 100
 
        xenrt.TEC().value("vhdddtime", vhdddtime, "s")
        xenrt.TEC().value("rawddtime", rawddtime, "s")
        xenrt.TEC().value("vhdddkbs", vhdddkbs, "kB/s")
        xenrt.TEC().value("rawddkbs", rawddkbs, "kB/s")
        xenrt.TEC().value("vhd/rawddkbs", ratio)

        if ratio < -self.MARGIN:
            # Bracket the degradation value to help autofiles.
            description = "%1.1f%%" % (ratio)
            for bracket in self.REPORT_BRACKETS:
                threshold, text = bracket  
                if not threshold:
                    description = text
                    break
                if ratio >= -float(threshold):
                    description = text
                    break 
            raise xenrt.XRTFailure("Performance of dd decreased by %s." % (description))

class _TCLVHDLeafCoalesce(xenrt.TestCase):

    # Scenarios
    SCENARIO_SINGLE_VBD = 1
    SCENARIO_TWO_VBDS_SAME_SR = 2
    SCENARIO_TWO_VBDS_DIFFERENT_SRS = 3
    SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE = 4
    SCENARIO_SINGLE_VBD_RESIZED = 5 # Resize should be in the HISTORY

    # Test config
    SRTYPE = "lvm"
    SRTYPE_SECOND_VDI = None
    ORIGINAL_VDI_TYPE = "VHD" # or LV for legacy
    SR_ON_MASTER = True # Only needed for non-shared SRs
    UTILITY_ON_MASTER = True # Where we run the leaf node coalesce script
    VM_STATE = "UP" # or "DOWN" or "SUSPENDED"
    HISTORY = [("snapshot", "snap1"), ("delete", "snap1")]
    SCENARIO = SCENARIO_SINGLE_VBD
    WINDOWS = False
    RETRY_CHECK_VDI_CHAINS = 5

    def writePatternToFile(self, filename, patternid=0):
        """Write a 1GB deterministic pattern to a file"""
        if self.guest.windows:
            raise xenrt.XRTError("writePatternToFile not implemented for "
                                 "Windows")
        else:
            cmd = "%s/remote/patterns.py %s 1073741824 write 1 %u" % \
                  (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), filename, patternid)
            self.guest.execguest(cmd)

    def writePatterns(self, fileid):
        """Write patterns to all VBDs of the VM. Return the list of pattern
        IDs used for each VBD."""
        vbdpatterns = []
        for i in range(self.vbdcount):
            pattern = random.randint(0, 1073741824)
            vbdpatterns.append(pattern)
            filename = "/VDI%d/pattern%d.dat" % (i, fileid)
            xenrt.TEC().logverbose("Writing pattern %d to %s" %
                                   (pattern, filename))
            self.writePatternToFile(filename, pattern)
        return vbdpatterns

    def checkPatternInFile(self, filename, patternid=0):
        """Check a deterministic pattern in a file"""
        if self.guest.windows:
            raise xenrt.XRTError("checkPatternInFile not implemented for "
                                 "Windows")
        else:
            cmd = "%s/remote/patterns.py %s 1073741824 read 1 %u" % \
                  (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), filename, patternid)
            self.guest.execguest(cmd)

    def checkPatterns(self):
        """Check all patterns in all VDIs"""
        for i in range(len(self.vbdpatternlist)):
            vbdpatterns = self.vbdpatternlist[i]
            for j in range(self.vbdcount):
                pattern = vbdpatterns[j]
                filename = "/VDI%d/pattern%d.dat" % (j, i)
                xenrt.TEC().logverbose("Checking pattern %d in %s" %
                                       (pattern, filename))
                self.checkPatternInFile(filename, pattern)

    def waitForCoalesce(self):
        """Wait for all SRs involved in this test to complete any outstanding
        coalesce activity."""
        for sr in self.srs:
            xenrt.TEC().logverbose("Waiting for coalesce of SR %s" % (sr))
            host = self.srmasters[sr]
            host.waitForCoalesce(sr)

    def displayDebug(self):
        """Log a debug dump of the SRs' VHD structures"""
        for sr in self.srs:
            self.host.vhdSRDisplayDebug(sr)

    def getSRsFreeSpace(self):
        """Return a dictionary keyed by SR of free space in bytes"""
        reply = {}
        for sr in self.srs:
            size = int(self.host.genParamGet("sr", sr, "physical-size"))
            utilisation = int(self.host.genParamGet("sr",
                                                    sr,
                                                    "physical-utilisation"))
            reply[sr] = size - utilisation
        return reply

    def prepare(self, arglist):

        self.host = self.getDefaultHost()

        # Find a suitable SR
        self.srmasters = {}
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.srs = [srs[0]]
        if self.SRTYPE_SECOND_VDI:
            srs = self.host.getSRs(type=self.SRTYPE_SECOND_VDI)
            if not srs:
                raise xenrt.XRTError("No %s SR found on host." %
                                     (self.SRTYPE_SECOND_VDI))
            self.srs.append(srs[0])

        # Find SRmasters for each SR
        if self.host.pool:
            hosts = self.host.pool.getHosts()
        else:
            hosts = [self.host]
        for sr in self.srs:
            host = None
            pbds = self.host.getSRParam(sr, "PBDs").split(";")
            if len(pbds) == 1:
                for h in hosts:
                    u = self.host.genParamGet("pbd", pbds[0], "host-uuid")
                    if h.getMyHostUUID() == u:
                        host = h
                        break
            else:
                # Assume it's a shared SR with the pool master running
                # the coalesce
                host = self.host
            if not host:
                raise xenrt.XRTError("Could not determine SR master for SR %s"
                                     % (sr))
            self.srmasters[sr] = host

        # Install a VM
        if self.ORIGINAL_VDI_TYPE == "LV":
            # Set a FIST point to ensure a legacy raw VDI is created.
            self.srmasters[self.srs[0]].execdom0(\
                "touch /tmp/fist_xenrt_default_vdi_type_legacy")
        try:
            if self.WINDOWS:            
                self.guest = self.host.createGenericWindowsGuest(sr=self.srs[0])
            else:
                self.guest = self.host.createGenericLinuxGuest(\
                    sr=self.srs[0])
            self.uninstallOnCleanup(self.guest)
        finally:
            if self.ORIGINAL_VDI_TYPE == "LV":
                # Remove the FIST point
                self.srmasters[self.srs[0]].execdom0(\
                    "rm -f /tmp/fist_xenrt_default_vdi_type_legacy")

        # Set up the correct number of VDIs/VBDs
        vbds = self.guest.listVBDUUIDs("Disk")
        if len(vbds) == 0:
            raise xenrt.XRTError("Guest has no VBDs")
        if len(vbds) > 1:
            # Probably a Debian VM with a swap disk, remove it.
            if self.guest.windows:
                raise xenrt.XRTError("Windows guest has more than one VBD")
            self.guest.execguest("swapoff -a")
            self.guest.execguest("sed -e 's/.*swap.*//' -i /etc/fstab")
            self.guest.shutdown()
            # Assume it's userdevice 1
            self.guest.removeDisk("1")
            self.guest.start()
            vbds = self.guest.listVBDUUIDs("Disk")
            if len(vbds) > 1:
                raise xenrt.XRTError("Guest still has more than one VBD "
                                     "after removing swap")
        self.vbdcount = 1
        if self.SCENARIO in (self.SCENARIO_TWO_VBDS_SAME_SR,
                             self.SCENARIO_TWO_VBDS_DIFFERENT_SRS,
                             self.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE):
            # Add a second VBD
            if self.guest.windows:
                raise xenrt.XRTError("Two VBD scenarios not supported by "
                                     "testcase for Windows VM")
            if self.SCENARIO == self.SCENARIO_TWO_VBDS_SAME_SR:
                sr2 = self.srs[0]
            else:
                if len(self.srs) < 2:
                    raise xenrt.XRTError("No second SR specified in TC")
                sr2 = self.srs[1]
            if self.ORIGINAL_VDI_TYPE == "LV":
                # Set a FIST point to ensure a legacy raw VDI is created.
                self.srmasters[sr2].execdom0(\
                    "touch /tmp/fist_xenrt_default_vdi_type_legacy")
            try:
                self.extradisk = self.guest.createDisk(sizebytes=4*xenrt.GIGA,
                                                       sruuid=sr2,
                                                       userdevice="1",
                                                       returnDevice=True)
            finally:
                if self.ORIGINAL_VDI_TYPE == "LV":
                    # Remove the FIST point
                    self.srmasters[sr2].execdom0(\
                        "rm -f /tmp/fist_xenrt_default_vdi_type_legacy")
            time.sleep(30)
            self.guest.execguest("mkfs.ext3 -F /dev/%s" % (self.extradisk))
            self.guest.execguest("mkdir /VDI1")
            self.guest.execguest("echo '/dev/%s /VDI1 ext3 defaults 0 0' > "
                                 "/etc/fstab" % (self.extradisk))
            self.guest.execguest("mount /VDI1")
            self.vbdcount = self.vbdcount + 1

            if self.SCENARIO == self.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE:
                # Perform a VDI.snapshot of the second VBD to give it
                # a longer chain length than the first VBD
                vdiuuid = self.guest.getDiskVDIUUID("1")
                self.host.getCLIInstance().execute("vdi-snapshot",
                                                   "uuid=%s" % (vdiuuid))

        # Check all VDIs are of the expected type
        self.doVDITypeCheck()

        # Write data patterns to VM's VBDs
        self.vbdpatternlist = []
        if self.guest.windows:
            self.guest.xmlrpcCreateDir("c:\\VDI0")
        else:
            self.guest.execguest("mkdir /VDI0")
        if not self.WINDOWS:
            self.vbdpatternlist.append(\
                self.writePatterns(len(self.vbdpatternlist)))

        # Record SR free space
        self.waitForCoalesce()
        time.sleep(120)
        self.freeSpaceBeforeSnapshot = self.getSRsFreeSpace()
        self.extraSpaceUsed = {}
        for sr in self.srs:
            self.extraSpaceUsed[sr] = 0

        # Record the virtual and physical sizes of the VDIs
        self.vdivirtualsizes = {} # bytes, keyed by disk ID
        self.vdiphysicalsizes = {} # bytes, keyed by disk ID
        for i in range(self.vbdcount):
            vdiuuid = self.guest.getDiskVDIUUID(str(i))
            vsize = int(self.host.genParamGet("vdi", vdiuuid, "virtual-size"))
            self.vdivirtualsizes[i] = vsize
            psize = self.host.getVDIPhysicalSizeAndType(vdiuuid)[0]
            self.vdiphysicalsizes[i] = psize

        # Perform required snapshot/delete/resize operations
        self.snapshots = {}
        for histstep in self.HISTORY:
            action, argument = histstep
            xenrt.TEC().logverbose("Performing action '%s' with argument '%s'"
                                   % (action, argument))
            if action == "snapshot":
                # Take a snapshot
                snapuuid = self.guest.snapshot(name=argument)
                self.snapshots[argument] = snapuuid
                if not self.WINDOWS:
                    self.vbdpatternlist.append(\
                        self.writePatterns(len(self.vbdpatternlist)))
            elif action == "delete":
                # Delete a snapshot
                if not argument in self.snapshots.keys():
                    raise xenrt.XRTError("No snapshot named '%s' found" %
                                         (argument))
                self.guest.removeSnapshot(self.snapshots[argument])
            elif action == "resize":
                # Resize a VDI on the VM (will ignore what happens inside
                # the VM (argument is disk index). Add 4GB.
                vdiuuid = self.guest.getDiskVDIUUID(argument)
                sr = self.host.genParamGet("vdi", vdiuuid, "sr-uuid")
                newsizemb = int((int(self.host.genParamGet("vdi",
                                                           vdiuuid,
                                                           "virtual-size"))
                                 + 4*xenrt.GIGA)/xenrt.MEGA)
                self.guest.shutdown()
                self.guest.resizeDisk(argument, newsizemb)
                self.guest.start()
                self.extraSpaceUsed[sr] = self.extraSpaceUsed[sr] + \
                                          4*xenrt.GIGA + \
                                          8388608 # VHD bitmap overhead
                self.vdivirtualsizes[int(argument)] = self.vdivirtualsizes[int(argument)] + 4*xenrt.GIGA
                self.vdiphysicalsizes[int(argument)] = self.vdiphysicalsizes[int(argument)] + 4*xenrt.GIGA
                if self.ORIGINAL_VDI_TYPE != "LV":
                    self.vdiphysicalsizes[int(argument)] = self.vdiphysicalsizes[int(argument)] + 8388608
            else:
                raise xenrt.XRTError("Unknown action '%s'" % (action))
            # Show our topology
            self.displayDebug()
            
        # Write more data patterns to the VM
        if not self.WINDOWS:
            self.vbdpatternlist.append(\
                self.writePatterns(len(self.vbdpatternlist)))

        # Put the VM into the required power state
        self.guest.setState(self.VM_STATE)

        # Wait for any GC to complete
        self.waitForCoalesce()

        # Show our topology
        xenrt.TEC().logverbose("Dumping topology state after TC prepare")
        self.displayDebug()
        self.freeSpaceBeforeLeafCoalesce = self.getSRsFreeSpace()
        
    def doLeafCoalesce(self):
        if self.UTILITY_ON_MASTER:
            host = self.srmasters[self.srs[0]]
        else:
            # Find a host that is not the SR master of the first SR
            if self.host.pool:
                hosts = self.host.pool.getHosts()
            else:
                hosts = [host]
            host = None
            for h in hosts:
                if h.getMyHostUUID() != \
                       self.srmasters[self.srs[0]].getMyHostUUID():
                    host = h
                    break
            if not host:
                raise xenrt.XRTError("Could not find a host that is not "
                                     "the SR master")
        try:
            if host.execdom0("ls /opt/xensource/bin/coalesce-leaf", retval="code"):
                self.guest.leafCoalesce(hostuuid=host.getMyHostUUID())
            else:
                host.execdom0("/opt/xensource/bin/coalesce-leaf -u %s" %
                              (self.guest.getUUID()))
        except xenrt.XRTFailure, e:
            if self.UTILITY_ON_MASTER:
                raise e
            # Check for expected failure mode
            if self.SRTYPE in ("lvm", "ext"):
                expected = ["not attached on this host",
                            "This host is NOT the SRMaster",
                            "no leaf-coalesceable VDIs"
                           ]
            else:
                expected = ["This host is NOT master",
                            "no leaf-coalesceable VDIs"
                           ]
            match = False
            for x in expected:
                if x in e.data:
                    match = True
                    break
            if match:
                pass
            else:
                raise xenrt.XRTFailure(\
                    "Unexpected failure output from running utility on "
                    "non-master host: %s" % (str(e)), e.data)
        else: 
            if not self.UTILITY_ON_MASTER:
                raise xenrt.XRTFailure("Utility did not raise an error when "
                                       "run on a non-master host")

    def doCheckState(self):
        actual = self.guest.getState()
        if actual != self.VM_STATE:
            raise xenrt.XRTFailure("VM in unexpected %s state after "
                                   "coalesce, expecting %s" %
                                   (actual, self.VM_STATE))

    def doCheckFreeSpace(self):
        errors = 0
        freeSpace = self.getSRsFreeSpace()
        for sr in self.srs:
            presnap = self.freeSpaceBeforeSnapshot[sr]
            preleafgc = self.freeSpaceBeforeLeafCoalesce[sr]
            now = freeSpace[sr]
            xenrt.TEC().logverbose("SR %s free space: %db before snapshot, "
                                   "%db before leaf coalesce, "
                                   "%db after leaf coalesce. "
                                   "VDI.resize added %db" %
                                   (sr,
                                    presnap,
                                    preleafgc,
                                    now,
                                    self.extraSpaceUsed[sr]))
            # If we resized a VDI in this SR then remove the resized space and
            # overhead from the presnap value
            presnap = presnap - self.extraSpaceUsed[sr]
            if now < presnap:
                errors = errors + 1
        if errors > 0:
            raise xenrt.XRTFailure("Free space after leaf coalesce is "
                                   "less than before snapshot")

    def doSmoketest(self):
        self.guest.reboot()
        self.guest.suspend()
        self.guest.resume()
        self.guest.shutdown()
        self.guest.start()

    def doCheckChains(self):
        # Check each of our VDIs has no vhd-parent
        for i in range(self.vbdcount):
            vdiuuid = self.guest.getDiskVDIUUID(str(i))
            if i == 1 and \
                   self.SCENARIO == self.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE:
                # This VBD is still expected to have a parent
                xenrt.TEC().logverbose("Checking the second VDI still has"
                                       "a parent")
                vhdparent = self.host.genParamGet("vdi",
                                                  vdiuuid,
                                                  "sm-config",
                                                  "vhd-parent")
                parent = self.host.vhdQueryParent(vdiuuid)
                if not parent:
                    raise xenrt.XRTFailure(\
                        "Non-coalescable VDI missing parent")
                if parent != vhdparent:
                    raise xenrt.XRTFailure(\
                        "Non-coalescable VDI parent mismatch")
                continue
                
            vhdparent = None
            try:
                vhdparent = self.host.genParamGet("vdi",
                                                  vdiuuid,
                                                  "sm-config",
                                                  "vhd-parent")
            except xenrt.XRTFailure, e:
                if "Key vhd-parent not found in map" in e.data:
                    # Expected
                    pass
                else:
                    raise e            
                    
            if vhdparent:
                raise xenrt.XRTError("VDI still has vhd-parent after leaf "
                                     "coalesce", vdiuuid)
            if self.host.vhdQueryParent(vdiuuid):
                raise xenrt.XRTError("VDI's VHD still has a parent after leaf"
                                     "coalesce", vdiuuid)

    def doVDISizeCheck(self):
        # For each VDI the VM has check the reported virtual-size is
        # as expected and the on-disk physical size is correct (i.e.
        # virtual-size plus metadata overhead.
        for i in range(self.vbdcount):
            vdiuuid = self.guest.getDiskVDIUUID(str(i))
            vsize = int(self.host.genParamGet("vdi", vdiuuid, "virtual-size"))
            psize = self.host.getVDIPhysicalSizeAndType(vdiuuid)[0]
            if self.vdivirtualsizes[i] != vsize:
                raise xenrt.XRTFailure("VBD virtual size mismatch for %u" %
                                       (i),
                                       "Is %ub, expected %ub" %
                                       (vsize, self.vdivirtualsizes[i]))
            if self.vdiphysicalsizes[i] != psize:
                sruuid = self.host.genParamGet("vdi", vdiuuid, "sr-uuid")
                sr = xenrt.lib.xenserver.getStorageRepositoryClass(self.host, sruuid).fromExistingSR(self.host, sruuid)
                if sr.thinProvisioning:
                    if psize > self.vdiphysicalsizes[i]:
                        if xenrt.TEC().lookup("WORKAROUND_CA171836", False, boolean=True):
                            xenrt.TEC().logverbose("VBD physical size of %u is bigger than virtual size in thin provisioning SR." %
                                       (i),
                                       "Is %ub, expected smaller than %ub" %
                                       (psize, self.vdiphysicalsizes[i]))
                        else:
                            raise xenrt.XRTFailure("VBD physical size of %u is bigger than virtual size in thin provisioning SR." %
                                       (i),
                                       "Is %ub, expected smaller than %ub" %
                                       (psize, self.vdiphysicalsizes[i]))
                else:
                    raise xenrt.XRTFailure("VBD physical size mismatch for %u" %
                                       (i),
                                       "Is %ub, expected %ub" %
                                       (psize, self.vdiphysicalsizes[i]))

    def doVDITypeCheck(self):
        # Check all VDIs are of the expected type
        for i in range(self.vbdcount):
            vdiuuid = self.guest.getDiskVDIUUID(str(i))
            vditype = self.host.getVDIPhysicalSizeAndType(vdiuuid)[1]
            expected = self.ORIGINAL_VDI_TYPE
            if i == 1 and \
                   self.SCENARIO == self.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE:
                # If the original was LV and not coalescable then the 
                # current one will be VHD because it is a child
                expected = "VHD"
            if vditype != expected:
                raise xenrt.XRTError("VDI for device %u is not the expected "
                                     "%s type (is %s)" %
                                     (i, self.ORIGINAL_VDI_TYPE, vditype))

    def run(self, arglist):

        # Run the leaf coalesce script on this VM
        if self.runSubcase("doLeafCoalesce", (), "Coalesce", "Leaf") \
               != xenrt.RESULT_PASS:
            return            

        # Check the VM is still in the same state it was before
        self.runSubcase("doCheckState", (), "Guest", "State")

        # Put the VM back into a running state if necessary
        self.guest.setState("UP")

        if self.UTILITY_ON_MASTER:
            # Check SR free space
            self.waitForCoalesce()
            self.runSubcase("doCheckFreeSpace", (), "SR", "FreeSpace")

            # Check VDI chains are now of length 1
            retries = self.RETRY_CHECK_VDI_CHAINS
            while retries:
                try:
                    self.runSubcase("doCheckChains", (), "Guest", "Chains")
                    break
                except xenrt.XRTError, e:
                    xenrt.TEC().logverbose("VDI still has parent-VHD after leaf coalesce; retrying checking in 60s ...")
                    xenrt.sleep(60)
                    retries = retries -1
                    if not retries:
                        raise 
                except Exception, e:
                    raise 
                       
        # Verify the in-VM data patterns
        if not self.WINDOWS:
            self.runSubcase("checkPatterns", (), "Guest", "Patterns")

        if self.UTILITY_ON_MASTER:
            # Check the size of the VM's VBDs are as expected, taking
            # account of any resize operation
            self.runSubcase("doVDISizeCheck", (), "Guest", "VDISize")

            # Check the types are still what we expect
            self.runSubcase("doVDITypeCheck", (), "Guest", "VDIType")

        # VM operations smoketest
        if self.runSubcase("doSmoketest", (), "Guest", "Lifecycle") \
               != xenrt.RESULT_PASS:
            return

        # Show our topology
        self.displayDebug()

class TC10560(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on local LVM SR"""
    pass

class TC10561(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with two VHDs on local LVM SR"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR

class TC10562(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]

class TC10563(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a halted VM with one VHD on local LVM SR"""
    
    VM_STATE = "DOWN"
    
class TC10564(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a halted VM with two VHDs on local LVM SR"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "DOWN"

class TC10565(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a halted VM with one VHD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "DOWN"

class TC10566(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a suspended VM with one VHD on local LVM SR"""
    
    VM_STATE = "SUSPENDED"
    
class TC10567(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a suspended VM with two VHDs on local LVM SR"""
    
    SCENARIO =  _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "SUSPENDED"    

class TC10568(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a suspended VM with one VHD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "SUSPENDED"

class TC10577(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one legacy LVM VBD on local LVM SR"""

    ORIGINAL_VDI_TYPE = "LV"

class TC10578(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with two legacy LVM VBDs on local LVM SR"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    ORIGINAL_VDI_TYPE = "LV"

class TC10575(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one legacy LVM VBD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    ORIGINAL_VDI_TYPE = "LV"

class TC10576(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a halted VM with one legacy LVM VBD on local LVM SR"""
    
    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"

class TC10573(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a halted VM with two legacy LVM VBDs on local LVM SR"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"

class TC10574(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a halted VM with one legacy LVM VBD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"

class TC10571(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a suspended VM with one legacy LVM VBD on local LVM SR"""
    
    VM_STATE = "SUSPENDED"
    ORIGINAL_VDI_TYPE = "LV"
    
class TC10572(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a suspended VM with two legacy LVM VBDs on local LVM SR"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "SUSPENDED"
    ORIGINAL_VDI_TYPE = "LV"

class TC10570(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a suspended VM with one legacy LVM VBD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "SUSPENDED"
    ORIGINAL_VDI_TYPE = "LV"
    
class TC10579(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on local LVM SR after two snapshots and deletes"""
    HISTORY = [("snapshot", "snap1"),
               ("snapshot", "snap2"),
               ("delete", "snap1"),
               ("delete", "snap2")]

    
class TC10580(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one legacy LVM VBD on local LVM SR after two snapshots and deletes"""

    ORIGINAL_VDI_TYPE = "LV"

class TC10581(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on local LVM SR running the tool on the wrong host"""

    UTILITY_ON_MASTER = False
    
class TC10582(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on LVMoISCSI SR"""

    SRTYPE = "lvmoiscsi"

class TC10583(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHDs on LVMoISCSI SR and one on local LVM SR"""
    
    SRTYPE = "lvmoiscsi"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_DIFFERENT_SRS
    SRTYPE_SECOND_VDI = "lvm"
    
class TC10585(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on LVMoISCSI SR with the VHD being resized after the snapshot"""
    
    SRTYPE = "lvmoiscsi"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]

class TC10586(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a halted VM with one legacy LVM VBD on LVMoISCSI SR with tool run on the wrong host"""

    SRTYPE = "lvmoiscsi"
    UTILITY_ON_MASTER = False
    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"

class TC10587(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a suspended VM with two legacy LVM VBDs on LVMoISCSI SR with one not leaf-coalescable with tool run on the wrong host"""

    SRTYPE = "lvmoiscsi"
    SRTYPE_SECOND_VDI = "lvmoiscsi"
    UTILITY_ON_MASTER = False
    VM_STATE = "SUSPENDED"
    ORIGINAL_VDI_TYPE = "LV"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE
    
class TC10588(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one legacy LVM VBD on LVMoISCSI SR with the VDI having been resized after the snapshot with tool run on the wrong host"""

    SRTYPE = "lvmoiscsi"
    UTILITY_ON_MASTER = False
    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]

class TC10589(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on LVMoHBA SR"""

    SRTYPE = "lvmohba"

class TC10590(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with two VHDs on LVMoHBA SR"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"       
    
class TC10591(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on LVMoHBA SR and one on local LVM SR"""
    
    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_DIFFERENT_SRS
    SRTYPE_SECOND_VDI = "lvm"

class TC10592(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with two VHDs on LVMoHBA SR with one VHD not leaf-coalescable"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"

class TC10593(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one VHD on LVMoHBA SR with the VHD being resized after the snapshot"""
    
    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]

class TC10594(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one legacy LVM VDI on LVMoHBA SR"""

    SRTYPE = "lvmohba"
    ORIGINAL_VDI_TYPE = "LV"

class TC10595(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with two legacy LVM VDIs on LVMoHBA SR"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"
    ORIGINAL_VDI_TYPE = "LV"
    
class TC10596(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one legacy LVM VDI on LVMoHBA SR and one on local LVM SR"""
    
    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_DIFFERENT_SRS
    SRTYPE_SECOND_VDI = "lvm"
    ORIGINAL_VDI_TYPE = "LV"

class TC10597(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with two legacy LVM VDIs on LVMoHBA SR with one VHD not leaf-coalescable"""
    
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"
    ORIGINAL_VDI_TYPE = "LV"

class TC10598(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with one legacy LVM VDI on LVMoHBA SR with the VHD being resized after the snapshot"""
    
    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    ORIGINAL_VDI_TYPE = "LV"

class TC10599(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running VM with two VHDs on LVMoHBA SR having had two snapshots taken and deleted with tool run on the wrong host"""

    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"
    UTILITY_ON_MASTER = False
    ORIGINAL_VDI_TYPE = "LV"
    SCENARIO = _TCLVHDLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    HISTORY = [("snapshot", "snap1"),
               ("snapshot", "snap2"),
               ("delete", "snap1"),
               ("delete", "snap2")]

class TC10600(_TCLVHDLeafCoalesce):
    """Leaf node coalesce of a running Windows VM with one VHD on local LVM SR"""

    WINDOWS = True
    

class _TCLVHDOnlineLeafCoalesce(_TCLVHDLeafCoalesce):
    """Base class for online leaf coalesce functionality"""

    # The main difference between online leaf coalesce 
    # and offline leaf coalesce tests is that we don't have
    # to execute the script manually; it is part of gc thread

    def doLeafCoalesce(self):
        self.waitForCoalesce()

    
    def keepWriting(self):
        cmd = "nohup cat /dev/urandom > test 2> test.err < /dev/null &"
        self.guest.execguest(cmd, getreply=False)

class TC12013(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on local LVM SR"""
    pass

class TC12014(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with two VHDs on local LVM SR"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR

class TC12015(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]

class TC12016(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a halted VM with one VHD on local LVM SR"""
    
    VM_STATE = "DOWN"
    
class TC12017(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a halted VM with two VHDs on local LVM SR"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "DOWN"

class TC12049(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a halted VM with one VHD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "DOWN"

class TC12018(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a suspended VM with one VHD on local LVM SR"""
    
    VM_STATE = "SUSPENDED"
    
class TC12019(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a suspended VM with two VHDs on local LVM SR"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "SUSPENDED"

class TC12020(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a suspended VM with one VHD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "SUSPENDED"

class TC12028(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one legacy LVM VBD on local LVM SR"""

    ORIGINAL_VDI_TYPE = "LV"

class TC12029(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with two legacy LVM VBDs on local LVM SR"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    ORIGINAL_VDI_TYPE = "LV"

class TC12026(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one legacy LVM VBD on local LVM SR with the VHD being resized after the snapshot"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    ORIGINAL_VDI_TYPE = "LV"

class TC12027(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a halted VM with one legacy LVM VBD on local LVM SR"""

    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"

class TC12024(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a halted VM with two legacy LVM VBDs on local LVM SR"""

    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"

class TC12025(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a halted VM with one legacy LVM VBD on local LVM SR with the VHD being resized after the snapshot"""

    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "DOWN"
    ORIGINAL_VDI_TYPE = "LV"

class TC12022(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a suspended VM with one legacy LVM VBD on local LVM SR"""

    VM_STATE = "SUSPENDED"
    ORIGINAL_VDI_TYPE = "LV"
    
class TC12023(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a suspended VM with two legacy LVM VBDs on local LVM SR"""

    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    VM_STATE = "SUSPENDED"
    ORIGINAL_VDI_TYPE = "LV"

class TC12057(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a suspended VM with one legacy LVM VBD on local LVM SR with the VHD being resized after the snapshot"""

    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    VM_STATE = "SUSPENDED"
    ORIGINAL_VDI_TYPE = "LV"
    
class TC12030(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on local LVM SR after two snapshots and deletes"""
    HISTORY = [("snapshot", "snap1"),
               ("snapshot", "snap2"),
               ("delete", "snap1"),
               ("delete", "snap2")]

class TC12031(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one legacy LVM VBD on local LVM SR after two snapshots and deletes"""

    ORIGINAL_VDI_TYPE = "LV"
    HISTORY = [("snapshot", "snap1"),
               ("snapshot", "snap2"),
               ("delete", "snap1"),
               ("delete", "snap2")]

class TC12033(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on LVMoISCSI SR"""

    SRTYPE = "lvmoiscsi"

class TC12034(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHDs on LVMoISCSI SR and one on local LVM SR"""

    SRTYPE = "lvmoiscsi"
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_DIFFERENT_SRS
    SRTYPE_SECOND_VDI = "lvm"
    
class TC12035(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on LVMoISCSI SR with the VHD being resized after the snapshot"""

    SRTYPE = "lvmoiscsi"
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]

class TC12036(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on LVMoHBA SR"""

    SRTYPE = "lvmohba"

class TC12037(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with two VHDs on LVMoHBA SR"""

    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"
    
class TC12038(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on LVMoHBA SR and one on local LVM SR"""

    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_DIFFERENT_SRS
    SRTYPE_SECOND_VDI = "lvm"

class TC12039(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with two VHDs on LVMoHBA SR with one VHD not leaf-coalescable"""

    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"

class TC12040(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one VHD on LVMoHBA SR with the VHD being resized after the snapshot"""

    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]

class TC12041(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one legacy LVM VDI on LVMoHBA SR"""

    SRTYPE = "lvmohba"
    ORIGINAL_VDI_TYPE = "LV"

class TC12042(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with two legacy LVM VDIs on LVMoHBA SR"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_SAME_SR
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"
    ORIGINAL_VDI_TYPE = "LV"
    
class TC12043(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one legacy LVM VDI on LVMoHBA SR and one on local LVM SR"""
    
    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_DIFFERENT_SRS
    SRTYPE_SECOND_VDI = "lvm"
    ORIGINAL_VDI_TYPE = "LV"

class TC12044(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with two legacy LVM VDIs on LVMoHBA SR with one VHD not leaf-coalescable"""
    
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_TWO_VBDS_ONE_NOT_COALESCABLE
    SRTYPE = "lvmohba"
    SRTYPE_SECOND_VDI = "lvmohba"
    ORIGINAL_VDI_TYPE = "LV"

class TC12045(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM with one legacy LVM VDI on LVMoHBA SR with the VHD being resized after the snapshot"""
    
    SRTYPE = "lvmohba"
    SCENARIO = _TCLVHDOnlineLeafCoalesce.SCENARIO_SINGLE_VBD_RESIZED
    HISTORY = [("snapshot", "snap1"), ("resize", "0"), ("delete", "snap1")]
    ORIGINAL_VDI_TYPE = "LV"

class TC12046(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running Windows VM with one VHD on local LVM SR"""

    WINDOWS = True

class TC12424(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM heavily using the disk"""

    def run(self, arglist):

        # Start a process that continuously writes data to the disk
        self.keepWriting()
        
        # Trigger a coalesce run, which should fail
        try:
            self.waitForCoalesce()
        except:
            pass

        # Check the VM is still in the same state it was before
        self.runSubcase("doCheckState", (), "Guest", "State")

        # VM operations smoketest, which includes a reboot that stop the
        # random-write process
        if self.runSubcase("doSmoketest", (), "Guest", "Lifecycle") \
               != xenrt.RESULT_PASS:
            return

        # Put the VM back into a running state if necessary
        self.guest.setState("UP")

        # Retry leaf coalesce
        self.waitForCoalesce()

        # Check VDI chains are now of length 1
        self.runSubcase("doCheckChains", (), "Guest", "Chains")

        # Verify the in-VM data patterns
        self.runSubcase("checkPatterns", (), "Guest", "Patterns")
        
        # Show our topology
        self.displayDebug()

class TC12425(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM interrupted by host power cycle"""
    #self.host.machine.powerctl.cycle()
    
    def run(self, arglist):
        # CA-48450 Allow things to settle.
        time.sleep(360)

        # Start a process that continuously writes data to the disk
        self.keepWriting()

        # Trigger a coalesce run
        cli = self.host.getCLIInstance()
        cli.execute("sr-scan", "uuid=%s" % (self.srs[0]))
        time.sleep(5)
        
        # Power-cycle the host, which would brutally interrupt the coalesce
        self.host.machine.powerctl.cycle()

        # Wait for the host to be XAPI ready
        self.host.waitForSSH(900, desc="Host boot after power cycle")
        self.host.waitForEnabled(600, desc="Waiting for host to become enabled after powercycle")

        # Put the VM back into a running state if necessary
        self.guest.setState("UP")

        # Retry leaf coalesce
        self.waitForCoalesce()

        # Check VDI chains are now of length 1
        self.runSubcase("doCheckChains", (), "Guest", "Chains")

        # Verify the in-VM data patterns
        self.runSubcase("checkPatterns", (), "Guest", "Patterns")

        # VM operations smoketest
        if self.runSubcase("doSmoketest", (), "Guest", "Lifecycle") \
               != xenrt.RESULT_PASS:
            return

        # Show our topology
        self.displayDebug()

class TC12426(_TCLVHDOnlineLeafCoalesce):
    """Online Leaf node coalesce of a running VM interrupted by pool master change"""

    def run(self, arglist):

        # Start a process that continuously writes data to the disk
        self.keepWriting()

        # Trigger a coalesce run
        cli = self.host.getCLIInstance()
        cli.execute("sr-scan", "uuid=%s" % (self.srs[0]))
        time.sleep(5)
        
        # Designate new master
        slave = self.getHost("RESOURCE_HOST_1")
        pool = self.getDefaultPool()
        pool.designateNewMaster(slave)

        # Allow some time for the master transition to complete
        time.sleep(120)
        # Check the old master gets enabled
        self.host.waitForEnabled(300, desc="Waiting for old master to become enabled after designating new one")

        # Reboot VM
        self.guest.reboot()

        # Retry leaf coalesce
        self.waitForCoalesce()

        # Check VDI chains are now of length 1
        self.runSubcase("doCheckChains", (), "Guest", "Chains")

        # Verify the in-VM data patterns
        self.runSubcase("checkPatterns", (), "Guest", "Patterns")

        # VM operations smoketest
        if self.runSubcase("doSmoketest", (), "Guest", "Lifecycle") \
               != xenrt.RESULT_PASS:
            return

        # Show our topology
        self.displayDebug()



class TC15470(xenrt.TestCase):
    """Ensure that PBD get plugged after interrupted online leaf coalesce"""
    
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.snapshot = self.guest.snapshot()
        
    def run(self, arglist):
        # this is a script to kill xapi when a _leaf logical volume is found.
        
        scr = """#!/bin/bash
xe snapshot-uninstall snapshot-uuid=%s --force &
while [ 1 ]
do
  a=`lvs|grep leaf`
  if [[ ${#a} -gt 0 ]]
  then
    `killall xapi`
    exit 0
  fi
done
exit 1
""" % (self.snapshot)
        
        # write script to temp file on controller
        dir = xenrt.TEC().tempDir()
        tempFile = dir + "/CA68989"
        f = open(tempFile, "w")
        f.write(scr)
        f.close()
        
        # copy script to host
        sftp = self.host.sftpClient()
        try:
            sftp.copyTo(tempFile, "/root/CA68989")
        finally:
            sftp.close()
        
        # make script executable
        self.host.execdom0("chmod +x /root/CA68989")
        
        # execute script 
        self.host.execdom0("/root/CA68989")
        
        if not "leaf" in self.host.execdom0("lvs"):
            raise xenrt.XRTFailure("Failed to interrupt online leaf coalesce")
        
        # Xapi is now killed so powercycle the host and check everything comes back up
        self.host.machine.powerctl.cycle()
        self.host.waitForSSH(3600, "Host reboot")
        self.host.waitForEnabled(600, desc="Waiting for host to become enabled after powercycle")
        
        # now check the local-SR PBD is plugged
        pbds = self.host.minimalList("pbd-list",args="sr-uuid=%s" % (self.host.getLocalSR()))
        
        if self.host.genParamGet("pbd", pbds[0], "currently-attached") != "true":
            raise xenrt.XRTFailure("PBD not plugged after interupted leaf coalesce")
            
class TC20995(xenrt.TestCase):
    """Test for HFX 1042: Fix for VBD out of sync xapi fix"""
    def prepare(self, arglist):
        self.pool=self.getDefaultPool()
        self.slave=self.pool.getSlaves()[0]

        # Create nfs SR
        nfs = xenrt.resources.NFSDirectory()
        nfsdir = xenrt.command("mktemp -d %s/nfsXXXX" %
                (nfs.path()), strip=True)
        sr = xenrt.lib.xenserver.NFSStorageRepository(self.pool.master,
                                                        "nfssr")
        server,path = nfs.getHostAndPath(os.path.basename(nfsdir))
        sr.create(server, path)
        self.nfsuuid=sr.uuid
        
    def createAndPlugVBD(self, host, name, sruuid=None, size=5424509440, plug=True):
        """To create a vdi, vhd and plug it to the host"""
        cli=host.getCLIInstance()
        args = []
        args.append("name-label=%s" % name)
        args.append("virtual-size=%i" % size)
        args.append("type=user")
        args.append("sr-uuid=%s" % sruuid)
        vdiuuid = cli.execute("vdi-create", string.join(args), 
                            strip=True)
        # Attach it to dom0
        args = []
        args.append("vdi-uuid=%s" % (vdiuuid))
        args.append("vm-uuid=%s" % host.getMyDomain0UUID())
        args.append("type=Disk")
        args.append("device=0")
        vbd = cli.execute("vbd-create",
                        string.join(args)).strip()
        if plug:
            cli.execute("vbd-plug", "uuid=%s" % (vbd))

        return vdiuuid, vbd

    def run(self, arglist):
        xenrt.log("Creating vdi to attach to Dom0")
        vdiuuid, vbd = self.createAndPlugVBD(host=self.slave,
                                            name="TestVDI1",
                                            sruuid=self.nfsuuid)

        # Now delete the vhd
        path="/var/run/sr-mount/%s/%s.vhd" % (self.nfsuuid, vdiuuid)
        xenrt.log("Deleting vhd at %s" % path)
        self.slave.execdom0('rm %s' % path)

        # Verify inconsistency in reporting
        cli=self.slave.getCLIInstance()
        cli.execute('sr-scan', 'uuid=%s' % self.nfsuuid)
        vlist=cli.execute('vbd-list')
        xenrt.log(vlist)

        # Repro-ing the issue here
        # Sleep to allow GC to run
        tries=0
        while self.slave.minimalList("vbd-list") and tries <2:
            xenrt.sleep(60)
            tries+=1

        vdiuuid, vbd = self.createAndPlugVBD(host=self.slave,
                                            name="TestVDI2",
                                            plug=False,
                                            sruuid=self.nfsuuid)
        try:
            cli.execute("vbd-plug", "uuid=%s" % (vbd))
        except Exception,e:
            xenrt.TEC().logerror("Caught exception as expected - %s " % e)
            if not re.search("already connected", e.data, re.I):
                raise e
        self.slave.restartToolstack()
        
        xenrt.sleep(10)

        try:
            cli.execute("vbd-unplug", "uuid=%s" % vbd)
        except Exception, e:
            xenrt.TEC().logerror("Caught exception as expected - %s " % e)
            # Ensure we have the right exception
            if not re.search("Db_exn.DBCache_NotFound", e.data, re.I) or \
            re.search("Storage_access.No_VDI", e.data, re.I):
                raise e

class TC21727(xenrt.TestCase):

    """Test for automating SCTX 1536"""
    SRTYPE = "nfs"
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        step("Create a Linux guest........")
        self.guest=self.host.createGenericLinuxGuest(name="linuxGuest")
        
        step("Create a NFS SR and get its UUID to create VDIs........")
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(self.host, self.SRTYPE)
        nfsSR.create()
        self.host.addSR(nfsSR, default=True)
        self.sr = nfsSR.uuid

        step("Create a VDI of size 16MB on NFS SR........")

        self.vdi=self.host.createVDI(16*xenrt.MEGA,sruuid=self.sr,smconfig=None)
        
        step("Create a VBD to attach the VM to 16MB VDI......")

        self.deviceVbd = self.guest.createDisk(vdiuuid=self.vdi,returnDevice=True)
        
        step("Create a 1GB VDI on NFS SR - This will be used to take snapshots........")

        self.vdiForSnapshot=self.host.createVDI(1*xenrt.GIGA,sruuid=self.sr,smconfig=None)
        
        step("Create 5 snapshots of the 1GB VDI........")
        self.snapshotVdi=[]
        for i in range(0,5):
            x = self.host.snapshotVDI(self.vdiForSnapshot)
            self.snapshotVdi.append(x)
            
    def run(self, arglist=None):
        step("Copy the footer file from the .vhd file for 5th snapshot created for 1GB VDI........")
        step("Here, we first get the size of the .vhd file of the snapshot and calculate the blocks to seek as (number of blocks= size of vhd file in Bytes/ 512).........")

        
        self.dataVhdFile = self.host.execdom0("ls -al /var/run/sr-mount/%s/%s.vhd" %(self.sr,self.snapshotVdi[4])).strip()
        self.sizeBytesSnapshotVhd = self.dataVhdFile.split()[4]
        
        step("We navigate to the actual footer file's beginning which is the last block in .vhd file. Hence, we do a blocksize - 1 operation........")

        self.footerHostSkip = (((int(self.sizeBytesSnapshotVhd))/512)-1)
        
        self.host.execdom0("dd if=/var/run/sr-mount/%s/%s.vhd of=/footer skip=%d bs=512" %(self.sr,self.snapshotVdi[4], self.footerHostSkip))

        step("Secure copy the footer file from host to Debian guest.........")
        step("Create a tmp directory on the controller that will be automatically cleaned up...........")

        ctrlTmpDir = xenrt.TEC().tempDir()

        step("copy footer file of .vhd to tempdir on controller.........")
        filePathController = os.path.basename("/footer")
        sftp = self.host.sftpClient()

        try:
            sftp.copyFrom("/footer", os.path.join(ctrlTmpDir,filePathController))
        finally:
            sftp.close()

        step("copy footer file of .vhd from tempdir on controller to guest...........")

        sftp = self.guest.sftpClient()
        try:
            sftp.copyTo(os.path.join(ctrlTmpDir,filePathController), os.path.join('/tmp',filePathController))
        finally:
            sftp.close()

        step("Calculate the location to footer file of the debian guest's VBD. this is done by calculating the total number of blocks in the guest's VBD and then subtracting it by 1......")
        
        blockDev = self.guest.execguest("blockdev --getsz /dev/%s" %(self.deviceVbd))
        blockDeviceGuestFooter = int(blockDev)-1

        step("Overwrite the footer file on guest's VBD with that from snapshot VDI's.........")

        self.guest.execguest("dd if=/tmp/footer of=/dev/%s seek=%d count=1" %(self.deviceVbd,blockDeviceGuestFooter))

        self.guest.reboot()
        xenrt.TEC().logverbose("self.guest.reboot() completed")



    def postrun(self):
        step("Destroy all snapshot VDIs...........")
        for uuid in self.snapshotVdi:
            self.host.destroyVDI(uuid)
            
        step("Destroy 1GB VDI..............")
        self.host.destroyVDI(self.vdiForSnapshot)

        step("Destroy the guest created..............")
        try:
            self.guest.shutdown()
        except:
            pass
        try:
            self.guest.uninstall()
        except:
            pass

        step("Destroy the NFS SR created............")
        self.host.forgetSR(self.sr)
