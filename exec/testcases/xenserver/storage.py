
#
# XenRT: Test harness for Xen and the XenServer product family
#
# Storage tests
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, shutil, os.path, stat, re, glob, time, traceback, os
import xenrt, xenrt.lib.xenserver

class TCBigVHD(xenrt.TestCase):
    """Test the size limits of inidividual VHD VDIs."""

    def __init__(self, tcid="TCBigVHD"):
        xenrt.TestCase.__init__(self, tcid)
        self.guest = None
        
    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        bigsize = 2 * xenrt.MEGA - 8 * xenrt.KILO

        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." % (machine))
        self.getLogsFrom(host)

        self.guest = host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() == "UP":
            self.guest.shutdown()

        self.declareTestcase("BigVHD", "2Tb")
        self.declareTestcase("BigVHD", "TooBig")
        
        self.runSubcase("testVHD", (bigsize), "BigVHD", "2Tb")
        self.runSubcase("testVHD", (3*xenrt.MEGA), "BigVHD", "TooBig")

    def testVHD(self, size):
        disk = None
        
        if self.guest.getState() == "UP":
            xenrt.TEC().logverbose("Stopping guest before adding VDI.")
            self.guest.shutdown()

        sruuid = self.guest.host.getSRs(type="ext")[0]
        if not sruuid:
            xenrt.TEC().skip("No suitable SR found.")
        
        allowed = self.guest.host.genParamGet("vm",
                                               self.guest.getUUID(),
                                              "allowed-VBD-devices")
        device = str(min([int(x) for x in allowed.split("; ")]))

        # 2Tb is the upper limit on VDI size.
        if size > 2*xenrt.MEGA:
            try:
                self.guest.createDisk(sizebytes=size*xenrt.MEGA, sruuid=sruuid, userdevice=device)
                failure = "Created a disk of size %s, apparently." % (size)
            except:
                return
            raise xenrt.XRTFailure(failure)
        else:
            disk = self.guest.createDisk(sizebytes=size*xenrt.MEGA, sruuid=sruuid, userdevice=device)
            xenrt.TEC().logverbose("Created disk %s disk, %s." % (size, disk))

        self.guest.start()
        dev = self.guest.host.parseListForOtherParam("vbd-list",
                                                     "vm-uuid",
                                                      self.guest.getUUID(),
                                                     "device",
                                                     "userdevice=%s" % (disk))

        self.guest.execguest("mkfs.ext2 /dev/%s" % (dev), timeout=600)
        self.guest.execguest("mount /dev/%s /mnt" % (dev))
        self.guest.execguest("df -h")
        self.guest.execguest("umount /mnt")    
        self.guest.execguest("fsck -a /dev/%s" % (dev))
        
        self.guest.shutdown()
        self.guest.removeDisk(disk)

    def postRun(self):
        try:
            self.guest.shutdown()
        except:
            pass
        try:
            self.guest.uninstall()
        except:
            pass

class TCPlugTest(xenrt.TestCase):
    """Base class for hotplug tests."""

    def __init__(self, tcid="TCPlugTest"):
        xenrt.TestCase.__init__(self, tcid)
        self.guest = None
        self.disksToClean = []
        self.letter = None
        self.loops = None
        self.grace = None
        self.device = None

    def run(self, arglist=None):
        self.loops = 1
        self.grace = 30
        sizebytes = 10000000000
        guest = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                guest = l[1]
            elif l[0] == "loops":
                self.loops = int(l[1])
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]

        xenrt.TEC().logverbose("Using guest %s." % (guest))

        # Use an existing guest.
        self.guest = self.getGuest(guest)
        self.host = self.guest.host
        self.getLogsFrom(self.host)
        cli = self.host.getCLIInstance()
        if self.guest.getState() == "DOWN":
            xenrt.TEC().logverbose("Starting guest before commencing test.")
            self.guest.start()

        if self.guest.windows:
            before = self.guest.xmlrpcListDisks()
            xenrt.TEC().logverbose("Disks before: %s" % (before))

        xenrt.TEC().logverbose("Creating test disk.")
        self.device = self.guest.createDisk(sizebytes=sizebytes)
        self.disksToClean.append(self.device)
        time.sleep(self.grace)

         # Prepare disk.
        if self.guest.windows:
            after = self.guest.xmlrpcListDisks()
            xenrt.TEC().logverbose("Disks after: %s" % (after))
            for x in before:
                after.remove(x)
            disk = after[0]
            xenrt.TEC().logverbose("Partitioning disk %s." % (disk))
            self.letter = self.guest.xmlrpcPartition(disk)
            self.guest.xmlrpcFormat(self.letter)
            # Create an empty file a tenth of the size of the drive.
            xenrt.TEC().logverbose("Creating file on new disk...")
            self.guest.xmlrpcCreateEmptyFile("%s:\\data.tst" % (self.letter), 
                                                 sizebytes/(10*xenrt.MEGA))
        else:
            self.letter = self.host.parseListForOtherParam("vbd-list",
                                                           "vm-uuid",
                                                            self.guest.getUUID(),
                                                           "device",
                                                           "userdevice=%s" %
                                                            (self.device))
            xenrt.TEC().logverbose("Testing %s (%s)." % (self.device, self.letter)) 
            self.guest.execguest("mkfs.ext2 /dev/%s" % (self.letter))
            self.guest.execguest("mount /dev/%s /mnt" % (self.letter))
            self.guest.execguest("dd if=/dev/zero of=/mnt/data.tst bs=1M count=%s" % 
                                 (sizebytes/(100*xenrt.MEGA)))
        time.sleep(self.grace)

        # Run test specific loop.
        self.doLoop()

    def doLoop(self):
        raise xenrt.XRTError("Unimplemented.")

    def postRun(self):
        xenrt.TEC().logverbose("Cleaning disks : %s" % (self.disksToClean))
        try:
            if self.guest.getState() == "UP":
                self.guest.shutdown()
        except:
            pass
        for d in self.disksToClean:
            xenrt.TEC().logverbose("Cleaning disk %s." % (d))
            try:
                self.guest.unplugDisk(d)
            except:
                pass
            try:
                self.guest.removeDisk(d)
            except:
                pass        

class TCRePlugPersist(TCPlugTest):
    """XRT-1011. Checks that a disk which is hotplugged, 
       removed when the VM is down, and then hotplugged 
       again, persists."""

    def __init__(self, tcid="TCRePlugPersist"):
        TCPlugTest.__init__(self, tcid)

    def doLoop(self):
        vdiuuid = self.guest.getDiskVDIUUID(self.device)
        for i in range(self.loops):
            xenrt.TEC().progress("Starting loop %s of %s." % (i+1, self.loops))
            self.guest.shutdown()         
            self.guest.removeDisk(self.device, keepvdi=True)
            self.guest.start()
            self.guest.createDisk(userdevice=self.device, vdiuuid=vdiuuid)
            time.sleep(self.grace)
            xenrt.TEC().logverbose("Checking file is still present...")
            if self.guest.windows:
                if not self.guest.xmlrpcFileExists("%s:\\data.tst" % (self.letter)):
                    raise xenrt.XRTFailure("Couldn't find %s:\\data.tst." % (self.letter))
            else:
                self.guest.execguest("mount /dev/%s /mnt" % (self.letter))
                if not self.guest.execguest("ls -l /mnt/data.tst"):
                    raise xenrt.XRTFailure("Couldn't find /mnt/data.tst")

class TCPlugPersist(TCPlugTest):
    """Checks hotplugged disks persist across reboots."""

    def __init__(self, tcid="TCPlugPersist"):
        TCPlugTest.__init__(self, tcid)

    def doLoop(self):
        for i in range(self.loops):
            xenrt.TEC().progress("Starting loop %s of %s." % (i+1, self.loops))
            self.guest.reboot()         
            xenrt.TEC().logverbose("Checking file is still present...")
            if self.guest.windows:
                if not self.guest.xmlrpcFileExists("%s:\\data.tst" % (self.letter)):
                    raise xenrt.XRTFailure("Couldn't find %s:\\data.tst." % (self.letter))
            else:
                self.guest.execguest("mount /dev/%s /mnt" % (self.letter))
                if not self.guest.execguest("ls -l /mnt/data.tst"):
                    raise xenrt.XRTFailure("Couldn't find /mnt/data.tst")

class TCReplug(TCPlugTest):
    """Checks disks persist across live plugs and unplugs."""

    def __init__(self, tcid="TCReplug"):
        TCPlugTest.__init__(self, tcid)

    def doLoop(self):
    
        for i in range(self.loops):
            self.guest.execguest("umount /mnt")
            xenrt.TEC().progress("Starting loop %s of %s." % (i+1, self.loops))
            self.guest.unplugDisk(self.device)    
            time.sleep(self.grace)
            self.guest.plugDisk(self.device)
            time.sleep(self.grace)
            if self.guest.windows:
                if not self.guest.xmlrpcFileExists("%s:\\data.tst" % (self.letter)):
                    raise xenrt.XRTFailure("Couldn't find %s:\\data.tst." % (self.letter))
            else:
                self.guest.execguest("mount /dev/%s /mnt" % (self.letter))
                if not self.guest.execguest("ls -l /mnt/data.tst"):
                    raise xenrt.XRTFailure("Couldn't find /mnt/data.tst")

class TCMultipleVDI(xenrt.TestCase):

    def __init__(self, tcid="TCMultipleVDI"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []
        self.guestUninstall = False
        self.disksToClean = []
        self.shutdown = True

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        distro = "w2k3eer2"
        vcpus = None
        memory = None
        method = "HTTP"
        initial = 1
        max = 3     
        pxe = False
        arch = "x86-32"
        repository = None
        hotadd = False
        hotremove = False    
        sizebytes = 1000000000
        guestname = None
        clonevm = False

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "distro":
                distro = l[1]
            elif l[0] == "vcpus":
                vcpus = int(l[1])
            elif l[0] == "memory":
                memory = int(l[1])
            elif l[0] == "initial":
                initial = int(l[1])
            elif l[0] == "max":
                max = int(l[1])
            elif l[0] == "method":
                method = string.upper(l[1])
            elif l[0] == "pxe":
                pxe = True
            elif l[0] == "hotadd":
                hotadd = True
            elif l[0] == "hotremove":
                hotremove = True
            elif l[0] == "noshutdown":
                hotadd = True
                hotremove = True
            elif l[0] == "guest":
                guestname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
            elif l[0] == "clone":
                clonevm = True

        if guestname:
            # Use an existing guest.
            g = self.getGuest(guestname)

            if clonevm:
                self.blocker = False
                if g.getState() != "UP":
                    g.start()
                g.preCloneTailor()
                g.shutdown()
                clone = g.cloneVM()
                g = clone
                self.guestsToClean.append(g)
                self.guestUninstall = True
                g.start() 
                self.getLogsFrom(g)

            self.host = g.host
            self.getLogsFrom(self.host)
            cli = self.host.getCLIInstance()
            self.guestsToClean.append(g)
        else:
            # Create a guest.
            try:
                repository = string.split(\
                    xenrt.TEC().lookup(["RPM_SOURCE",
                                        distro,
                                        arch,
                                        method]))[0]
            except:
                pass

            self.host = xenrt.TEC().registry.hostGet(machine)
            if not self.host:
                raise xenrt.XRTError("Unable to find host %s in registry" %
                                     (machine))
            self.getLogsFrom(self.host)
            cli = self.host.getCLIInstance()
            
            template = xenrt.lib.xenserver.getTemplate(self.host, distro)

            # Install a guest with default disks.
            g = self.host.guestFactory()(\
                xenrt.randomGuestName(),
                template,
                password=xenrt.TEC().lookup("ROOT_PASSWORD_DEBIAN"))

            self.guestsToClean.append(g)
            self.guestUninstall = True

            if vcpus != None:
                g.setVCPUs(vcpus)
            if memory != None:
                g.setMemory(memory) 

            if xenrt.TEC().lookup(["CLIOPTIONS", "NOINSTALL"],
                                  False,
                                  boolean=True):
                xenrt.TEC().skip("Skipping because of --noinstall option")
                g.existing(self.host)
            else:
                if g.windows:
                    isoname = xenrt.DEFAULT
                else:
                    isoname = None
                g.install(self.host,
                          isoname=isoname,
                          distro=distro,
                          start=True,
                          repository=repository,
                          method=method,
                          pxe=pxe)
                if g.windows:
                    g.installDrivers()

        if xenrt.TEC().lookup("VIF_DEBUG", False, boolean=True):
            try:
                self.debugdom = g.getDomid()
                self.host.startVifDebug(self.debugdom)
            except:
                pass

        # Get a list of VBDs we already have. We won't mess with these.
        existingdevices = g.listDiskDevices()

        # Start with what we have already.
        basevbds = len(existingdevices) 
        nvbds = initial
        xenrt.TEC().comment("Found %u VBDs initially (%s)" %
                            (basevbds, string.join(existingdevices, ",")))
        
        # For each number of disks from the default to the specifed maximum
        # (inclusive). Offset by the "initial" argument.
        for i in range(0, (max - basevbds) + 1):
            # Check what we currently have.
            devices = g.listDiskDevices()
            xenrt.TEC().logverbose("Found %d VBDs." % (len(devices)))
        
            if nvbds < basevbds:
                # Never go below what we started with.
                xenrt.TEC().logverbose("Setting minimum VBDs to %d." % (basevbds))
                nvbds = basevbds 

            # Add or remove VBDs to get to the desired number.
            xenrt.TEC().logverbose("Changing number of VBDs to %d." % (nvbds))
            if nvbds > len(devices):
                # Need to add one or more VBDs.
                if not hotadd:
                    g.shutdown()
                for j in range(0, (nvbds - len(devices))):
                    d = g.createDisk(sizebytes=sizebytes)
                    time.sleep(10)
                    self.disksToClean.append(d)
                if hotadd:
                    # Allow time for the VM to notice the new disk(s)
                    time.sleep(60)
            elif nvbds < len(devices):
                # Need to remove one or more VBDs.
                if not hotremove:
                    g.shutdown()
                for j in range(0, (len(devices) - nvbds)):
                    dtr = self.disksToClean.pop()
                    if hotremove:
                        xenrt.sleep(30)
                        g.unplugDisk(dtr) 
                    g.removeDisk(dtr)   
            if g.getState() == "DOWN":            
                g.start()
                if g.distro and "vista" in g.distro:
                    # CA-31174 Allow time for the VM to notice the new disk(s)
                    time.sleep(120)
                
            # Check in the guest that we have the disks we should.
            xenrt.TEC().progress("Testing with %d VBDs." % (nvbds))
            devices = g.listDiskDevices()

            # Check each device we created in this loop.
            xenrt.TEC().comment("Verifying %u VBDs (%s)." %
                                (len(devices), string.join(devices, ",")))

            # On windows we don't know which vbd corresponds to which disk
            # so we just test all of them except the root disk.
            if g.windows:
                time.sleep(30)
                xenrt.TEC().logverbose("Listing disk information:")
                xenrt.TEC().logverbose(g.xmlrpcDiskInfo())

                # Get all the disks we want to test.
                disks = g.xmlrpcListDisks()

                xenrt.TEC().logverbose("Windows reports %s disks. (%s)" % (len(disks), disks))
                if not len(disks) == len(devices):
                    raise xenrt.XRTFailure("Number of disks reported by Windows (%s) "
                                           "doesn't match number reported by Domain-0 (%s)." %
                                           (len(disks), len(devices)))

                # We want to leave the root disk alone.
                rootdisk = g.xmlrpcGetRootDisk()
                xenrt.TEC().logverbose("Removing rootdisk (%s) from list." % (rootdisk))
                disks.remove(rootdisk)

                for disk in disks:
                    xenrt.TEC().logverbose("Listing disk information:")
                    xenrt.TEC().logverbose(g.xmlrpcDiskInfo())

                    time.sleep(30)
                    try:
                        xenrt.TEC().logverbose("Partitioning disk %s..." % (disk))
                        letter = g.xmlrpcPartition(disk)
                        xenrt.TEC().logverbose("Assigned letter %s." % (letter))
                    except Exception, e:
                        raise xenrt.XRTFailure("Partitioning failed. (%s)" % (str(e)))

                    xenrt.TEC().logverbose("Listing disk information:")
                    xenrt.TEC().logverbose(g.xmlrpcDiskInfo())

                    g.xmlrpcFormat(letter)
                    g.xmlrpcDeletePartition(letter)

                    xenrt.TEC().logverbose("Listing disk information:")
                    xenrt.TEC().logverbose(g.xmlrpcDiskInfo())
            else:            
                for device in devices:
                    if device in existingdevices: 
                        xenrt.TEC().logverbose("Not testing %s; not provisioned "
                                               "by this test." % (device))
                        continue
                    # Look up the guesttype-specific name.
                    dev = self.host.parseListForOtherParam("vbd-list",
                                                           "vm-uuid",
                                                            g.getUUID(),
                                                           "device",
                                                           "userdevice=%s" %
                                                           (device))
                    xenrt.TEC().logverbose("Testing %s (%s)." % (device, dev)) 
                    # On Linux we mkfs and mount/unmount each disk.
                    g.execguest("mkfs.ext2 /dev/%s" % (dev))
                    g.execguest("mount /dev/%s /mnt" % (dev))
                    g.execguest("umount /mnt")    

            nvbds = (nvbds + 1) % max
            if nvbds == 0:
                nvbds = max
        


    def postRun(self):
        if xenrt.TEC().lookup("VIF_DEBUG", False, boolean=True):
            try:
                self.host.stopVifDebug(self.debugdom)
            except:
                pass
        try:
            for g in self.guestsToClean:
                xenrt.TEC().logverbose("Starting postRun for %s." % (g.name))
                if g.getState() == "UP":
                    g.shutdown()
                for d in self.disksToClean:
                    try:
                        g.unplugDisk(d)
                    except:
                        pass
                    try:
                        g.removeDisk(d)
                    except:
                        pass
                if self.guestUninstall:
                    try:
                        g.shutdown(again=True)
                    except:
                        pass
                    g.uninstall()
        except:
            pass

class TCVBDPlug(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCVBDPlug")
        self.host = None
        self.disksToClean = []
        self.guest = None
        self.loops = None
        self.disksize = None
        self.maxDisks = None

    def run(self, arglist=None):

        gname = None
        loops = 50
        disksize = 100

        for arg in arglist[0:]:
            l = string.split(arg, "=", 1)
            if l[0] == "guest":
                gname = l[1]
            elif l[0] == "loops":
                loops = int(l[1])
            elif l[0] == "disksize":
                disksize = int(l[1])
            elif l[0] == "max":
                self.maxDisks = int(l[1])
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]

        if not gname:
            raise xenrt.XRTError("No guest name specified.")
        g = self.getGuest(gname)
        self.guest = g
        if not g:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                (gname))
        self.host = g.host

        if g.getState() != "UP":
            xenrt.TEC().comment("Starting guest %s before commencing test" %
                                (g.name))
            g.start()

        self.loops = loops
        self.disksize = disksize

        if g.windows:
            self.runWindows()
        else:
            self.runLinux()
            
    def runLinux(self):

        g = self.guest
        loops = self.loops
        disksize = self.disksize

        # Create a new VBD to (un)plug

        # Get the list of device names for VBDs we have already
        vbds = g.listVBDs()
        ds = vbds.keys()
        ds.sort()
        first = ds[0]
        last = ds.pop()

        # Use the same SR as the first disk
        u = g.getDiskVBDUUID(first)
        sruuid = g.host.getVBDSR(u)

        # Create a new disk in sequence
        device = last[0:-1] + chr(ord(last[-1]) + 1)
        d = g.createDisk(sizebytes=disksize * xenrt.MEGA, sruuid=sruuid, userdevice=device)
        self.disksToClean.append(d)

        dev = self.host.parseListForOtherParam("vbd-list",
                                               "vm-uuid",
                                               g.getUUID(),
                                               "device",
                                               "userdevice=%s" % (device))
                                               
        # Make a filesystem on this disk

        # On Linux we mkfs and mount/unmount each disk
        g.execguest("mkfs.ext2 /dev/%s" % (dev))
        g.execguest("mount /dev/%s /mnt" % (dev))
        g.execguest("umount /mnt")

        # Unplug the new VBD
        g.unplugDisk(d)

        success = 0
        try:
            for i in range(loops):
                g.plugDisk(d)
                if g.execguest("ls /sys/block/%s" % (dev),
                               retval="code") != 0:
                    raise xenrt.XRTFailure("Device %s not present in "
                                           "guest after plug" % (dev))
                g.execguest("mount /dev/%s /mnt" % (dev))
                g.execguest("umount /mnt")
                g.unplugDisk(d)
                if g.execguest("ls /sys/block/%s" % (dev),
                               retval="code") == 0:
                    raise xenrt.XRTFailure("Device %s still present in "
                                           "guest after unplug" % (dev))
                success += 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful." % (success, loops))

    def runWindows(self):
        g = self.guest
        disksize = self.disksize
        loops = self.loops

        # See what the largest VBD we can have is
        maxAllowed = max(map(int,
                self.host.genParamGet("vm",
                                       g.getUUID(),
                                      "allowed-VBD-devices").split("; ")))
        # Do we have a maximum parameter
        if self.maxDisks:
            maxDisks = min(maxAllowed,self.maxDisks)
        else:
            maxDisks = maxAllowed

        # Get the list of device names for VBDs we have already
        vbds = g.listVBDs()
        ds = vbds.keys()
        ds.sort()
        first = ds[0]
        last = ds.pop()

        # Use the same SR as the first disk
        u = g.getDiskVBDUUID(first)
        sruuid = g.host.getVBDSR(u)

        # Create a new disk in sequence
        device = int(last) + 1
        start_device = device

        success = 0
        try:
            for i in range(loops):
                # Create the maximum possible number of disks, plug each one,
                # then make a filesystem on it.
                # Then shutdown, destroy the disks, start up and loop
                disks = []
                
                for j in range(start_device,maxDisks+1):
                    disk = g.createDisk(sizebytes=disksize * xenrt.MEGA, sruuid=sruuid, userdevice=device)
                    self.disksToClean.append(disk)

                    # Format it
                    letter = self.formatWinDisk(device)

                    disks.append({'disk': disk, 'letter': letter})

                    device += 1

                # Remove the disks from windows
                for disk in disks:
                    self.removeWinDisk(disk['letter'])
                    # Sleep 15 seconds (otherwise windows gets annoyed)
                    time.sleep(15)

                # Shut down
                g.shutdown()

                # Destroy the disks
                for disk in disks:
                    g.removeDisk(disk['disk'])
                    self.disksToClean.remove(disk['disk'])

                # Now start the guest up again
                g.start()

                success += 1
                device = start_device
        finally:
            xenrt.TEC().comment("%u/%u iterations successful." % (success, loops))

    def formatWinDisk(self,device):
        """Format the newest disk on a Windows guest"""
        g = self.guest
        g.xmlrpcWriteFile("C:\\listdisk.txt","list disk")
        disks = g.xmlrpcExec("diskpart /s c:\\listdisk.txt",
                             returndata=True,
                             timeout=600)
        disks = re.findall("Disk [0-9]+", disks)
        disks = [ disk.replace("Disk ","") for disk in disks ]
        disks.remove("1")

        drive_letter = chr(65 + device)
        g.xmlrpcWriteFile("C:\\partition.txt","rescan\n"
                                               "list disk\n"
                                               "select disk %d\n"
                                               "clean\n"
                                               "create partition primary\n"
                                               "assign letter=%s\n" % 
                                               (int(disks[-1]), drive_letter))
        g.xmlrpcExec("diskpart /s c:\\partition.txt", timeout=600)
        g.xmlrpcFormat(drive_letter)
        return drive_letter

    def removeWinDisk(self,letter):
        g = self.guest
        g.xmlrpcWriteFile("c:\\partition.txt","select volume %s\n"
                                              "delete volume" % (letter))
        g.xmlrpcExec("diskpart /s c:\\partition.txt", timeout=600)

    def postRun(self):
        for d in self.disksToClean:
            try:
                self.guest.unplugDisk(d)
            except:
                pass
            try:
                self.guest.removeDisk(d)
            except:
                pass

class TCStorage(xenrt.TestCase):

    def __init__(self, tcid="TCStorage"):
        xenrt.TestCase.__init__(self, tcid)
        self.iscsi = None
        self.napp = None
        self.eql = None
        self.nfs = None
        self.commands = []
        self.testISCSI = True
        self.testNFS = True
        self.testNetApp = True
        self.testEQL = True
        self.testLVM = True
        self.testEXT = True
        self.srsTested = []
        self.capabilities = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))

        if arglist and len(arglist) > 1:
            for arg in arglist[1:]:
                l = string.split(arg,"=",1)
                if l[0] == "testTypes":
                    tt = l[1].split(",")
                    if not "iscsi" in tt:
                        self.testISCSI = False
                    if not "nfs" in tt:
                        self.testNFS = False
                    if not "netapp" in tt:
                        self.testNetApp = False
                    if not "eql" in tt:
                        self.testEQL = False
                    if not "lvm" in tt:
                        self.testLVM = False
                    if not "ext" in tt:
                        self.testEXT = False

        self.getLogsFrom(host)

        cli = host.getCLIInstance()
        # Remove local SRs so we can use the disk
        while True:
            try:
                sruuid = host.getLocalSR()
            except:
                # No more local SRs
                break
            # Remove any VDIs in the local SR (e.g. transfer VM)
            vdis = host.minimalList("vdi-list", args="sr-uuid=%s" % (sruuid))
            for vdi in vdis:
                cli.execute("vdi-destroy", "uuid=%s" % (vdi))
            pbdid = host.parseListForUUID("pbd-list", "sr-uuid", sruuid)
            cli.execute("pbd-unplug", "uuid=%s" % (pbdid))
            cli.execute("sr-destroy", "uuid=%s" % (sruuid))

        pooluuid = cli.execute("pool-list", "--minimal", strip=True)

        if xenrt.TEC().lookup("WORKAROUND_DEFPOOL", False, boolean=True):
            xenrt.TEC().warning("Using default pool workaround")
            cli.execute("pool-param-set",
                        "name-label=\"Default pool\" uuid=%s" % (pooluuid))

        cli.execute("pool-param-set", "uuid=%s other-config:force_loopback_vbd=true" % (pooluuid))

        if self.testLVM:
            self.srsTested.append("LVM")

        if self.testEXT:
            self.srsTested.append("ext")

        if self.testISCSI:
            # Get an iSCSI LUN for test use and set our local IQN
            lunconf = host.lookup("USE_ISCSI_SM", None)
            if lunconf:
                # This is an explicitly specified LUN
                self.iscsi = xenrt.lib.xenserver.host.ISCSILunSpecified(lunconf)
            else:
                minsize = int(host.lookup("SR_ISCSI_MINSIZE", 50))
                maxsize = int(host.lookup("SR_ISCSI_MAXSIZE", 1000000))
                self.iscsi = xenrt.lib.xenserver.host.ISCSILun(minsize=minsize,
                                                               maxsize=maxsize)
            host.setIQN(self.iscsi.getInitiatorName())
            self.srsTested.append("iSCSI")

        if self.testNetApp:
            # Get a NetApp target
            nappconf = host.lookup("USE_NETAPP_SM", None)
            if nappconf:
                # This is an explicitly specified target
                self.napp = \
                    xenrt.NetAppTargetSpecified(nappconf)
            else:
                minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                self.napp = xenrt.lib.xenserver.host.NetAppTarget(minsize=minsize, maxsize=maxsize)
            self.srsTested.append("NetApp")

        if self.testEQL:
            # Get an EqualLogic target
            eqlconf = host.lookup("USE_EQL_SM", None)
            if eqlconf:
                # This is an explicitly specified target
                self.eql = \
                    xenrt.EQLTargetSpecified(eqlconf)
            else:
                minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                self.eql = xenrt.lib.xenserver.host.EQLTarget(minsize=minsize, maxsize=maxsize)
            self.srsTested.append("EqualLogic")

        if self.testNFS:
            # First try a dedicated config
            nfs = xenrt.TEC().lookup("TCSTORAGE_NFS", None)
            if not nfs:
                # Otherwise get a general external NFS share
                x = xenrt.ExternalNFSShare()
                nfs = x.getMount()
            if not nfs:
                raise xenrt.XRTError("Could not find NFS server to use")
            r = re.search(r"([0-9\.]+):(\S+)", nfs)
            if not r:
                raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfs))
            self.nfs = (r.group(1), r.group(2))
            self.srsTested.append("NFS")

        # Get the test scripts
        testtarpath = xenrt.TEC().lookup("STORAGE_MANAGER_TESTS", None)
        testtar = None
        if testtarpath:
            testtar = xenrt.TEC().getFile(testtarpath)
        if not testtar:            
            # Try the same directory as the ISO
            testtar = xenrt.TEC().getFile("storage-manager-tests.tar",
                                          "xe-phase-1/storage-manager-tests.tar")
        if not testtar:
            raise xenrt.XRTError("No storage manager test tarball given")
        xenrt.command("tar -xf %s -C %s" % (testtar, self.tec.getWorkdir()))

        # Figure out what this version of SMRT can do
        f = "%s/tests/XE_api_library.sh" % (self.tec.getWorkdir())
        if os.path.exists(f):
            fh = file(f, "r")
            fdata = fh.read()
            fh.close()
            self.capabilities.extend(\
                re.findall(r"[A-Z0-9_]+\)\s*([A-Z0-9_]+)\=\$VAL", fdata))

        if "TOOLS_ROOT" in self.capabilities:            
            toolsDir = xenrt.WebDirectory()
            xenrt.getTestTarball("smrt", extract=True,
                                 directory=toolsDir.path())
            self.toolsRoot = toolsDir.getURL("smrt")

        # Apply any temporary workaround hacks
        if xenrt.TEC().lookup("WORKAROUND_APTGET", False, boolean=True):
            xenrt.TEC().warning("Using apt-get workaround")
            f = file("%s/tests/performance_functions.sh" %
                     (self.tec.getWorkdir()), "r")
            pf = f.read()
            f.close()
            aptupdate = """run $DOMU_REM_CMD "echo deb %s/debarchive etch main > /etc/apt/sources.list" """ % (xenrt.TEC().lookup("APT_SERVER"))
            pf = re.sub("bonnie_install\(\)\s*{",
                        "bonnie_install()\n{\n%s" % (aptupdate),
                        pf)
            f = file("%s/tests/performance_functions.sh" %
                     (self.tec.getWorkdir()), "w")
            f.write(pf)
            f.close()
        if xenrt.TEC().lookup("WORKAROUND_CA34963", True, boolean=True):
            # If we are using an older Etch export image for OEM then
            # we may have to remove xensource.list as well as citrix.list
            f = file("%s/tests/performance_functions.sh" %
                     (self.tec.getWorkdir()), "r")
            pf = f.read()
            f.close()
            pf = re.sub("/etc/apt/sources.list.d/citrix.list",
                        "/etc/apt/sources.list.d/citrix.list "
                        "/etc/apt/sources.list.d/xensource.list",
                        pf)
            f = file("%s/tests/performance_functions.sh" %
                     (self.tec.getWorkdir()), "w")
            f.write(pf)
            f.close()
        if xenrt.TEC().lookup("OPTION_SMRT_ETCH", False, boolean=True):
            xenrt.TEC().warning("Using Debian Etch for SMRT")
            f = file("%s/tests/XE_api_library.sh" %
                     (self.tec.getWorkdir()), "r")
            pf = f.read()
            f.close()
            pf = re.sub("Debian Sarge 3.1", "Debian Etch 4.0", pf)
            f = file("%s/tests/XE_api_library.sh" %
                     (self.tec.getWorkdir()), "w")
            f.write(pf)
            f.close()

        files = glob.glob("%s/tests/test*.sh" % (self.tec.getWorkdir()))
        tests = []        
        for f in files:
            tests.append(os.path.basename(f)[:-3])
        if len(tests) == 0:
            raise xenrt.XRTError("No storage manager tests found")
        tests.sort()
        skiplist = string.split(xenrt.TEC().lookup("STORAGE_SKIPS", ""), ",")
        allok = True
        for t in tests:
            if t in skiplist:
                xenrt.TEC().comment("Skipping %s" % (t))
            else:
                ok = self.dotest(host, t)
                allok = allok and ok

    def buildmessage(self, host, tests):
        r = xenrt.TEC().lookup(["CLIOPTIONS", "REVISION"], "")
        v = xenrt.TEC().lookup(["CLIOPTIONS", "VERSION"], "")
        if len(self.srsTested) > 0:
            et = " (%s)" % (string.join(self.srsTested, ","))
        else:
            et = ""
        n = host.getName()
        if n:
            e = " (host %s)" % (n)
        else:
            e = ""
        message = "XenRT Storage Manager test logs for %s %s%s%s\n" % \
            (v, r, et, e)
        jobid = xenrt.GEC().jobid()
        if jobid:
            message = message + "JobID: %u\n" % (jobid)
        message = message + "\n"
        for t in tests:
            message = message + "\n=== Test: %s ===\n" % (t)
            resfile = "%s/%s.log" % (self.tec.getLogdir(), t)
            if os.path.exists(resfile):
                f = file(resfile, "r")
                data = f.read()
                f.close()
                message =  message + data
            else:
                message =  message + "No log file.\n"
        for c in self.commands:
            message = message + "----------\n"
            message = message + c + "\n"
        return message

    def dotest(self, host, smtest):
        # Get a CLI instance for the test scripts to use
        cli = host.getCLIInstance()
        
        # Build the environment for the SM test scripts
        env = {}
        env['TEMPLATE_ALIAS'] = "debian"
        env['USERNAME'] = "root"
        if host.password:
            env['PASSWD'] = host.password
        else:
            env['PASSWD'] = xenrt.TEC().lookup("ROOT_PASSWORD")
        env['REMHOSTNAME'] = host.getIP()
        sshkey = xenrt.TEC().tempFile()
        shutil.copy(xenrt.TEC().lookup("SSH_PRIVATE_KEY_FILE"), sshkey)
        shutil.copy("%s.pub" % (xenrt.TEC().lookup("SSH_PRIVATE_KEY_FILE")),
                    "%s.pub" % (sshkey))
        os.chmod(sshkey, stat.S_IRWXU)
        os.chmod("%s.pub" % (sshkey), stat.S_IRWXU)
        env['SSH_PRIVATE_KEY'] = sshkey
        if self.iscsi:
            self.iscsi.setEnvTests(env)
        if self.napp:
            self.napp.setEnvTests(env)
            if not self.iscsi:
                env['IQN_INITIATOR_ID'] = host.getIQN()
        if self.eql:
            self.eql.setEnvTests(env)
            if not self.iscsi:
                env['IQN_INITIATOR_ID'] = host.getIQN()
        resfile = "%s/%s.log" % (self.tec.getLogdir(), smtest)
        env['DEBUG_FILE'] = resfile
        # If we have a PARTIONS variable defined in
        # /etc/firstboot.d/data/default-storage.conf then use the first
        # entry in that to determine the DEVSTRING. Otherwise fall back to
        # the (retail) default based on OPTION_CARBON_DISKS
        data = host.execdom0("cat /etc/firstboot.d/data/default-storage.conf "
                             "| cat")
        r = re.search(r"PARTITIONS=['\"]*([^'\"\s]+)", data)
        if r:
            env['DEVSTRING'] = r.group(1)
        else:
            primarydisk = string.split(host.lookup("OPTION_CARBON_DISKS",
                                                   "sda"))[0]
            env['DEVSTRING'] = xenrt.formPartition("/dev/%s" % (primarydisk),
                                                   3)
        br = host.getPrimaryBridge()
        if not br:
            raise xenrt.XRTError("Host has no bridge")
        env['BRIDGE'] = br
        env['NOCLEANUP'] = "true"
        if self.nfs:
            x, y = self.nfs
            env['NFSSERVER'] = x
            env['NFSSERVERPATH'] = y
        if not self.testLVM:
            # Make sure the test will grok this
            if "SKIP_LVM" in self.capabilities:
                env['SKIP_LVM'] = "yes"
        if not self.testEXT:
            if "SKIP_EXT" in self.capabilities:
                env['SKIP_EXT'] = "yes"
        # If we have a local apt-cacher us it
        env["APT_CACHER"] = "%s/debarchive" % xenrt.TEC().lookup("APT_SERVER")
        if "TOOLS_ROOT" in self.capabilities:
            env["TOOLS_ROOT"] = self.toolsRoot

        # Run the test script
        os.chmod("%s/tests/%s.sh" % (self.tec.getWorkdir(), smtest),
                 stat.S_IEXEC | stat.S_IREAD | stat.S_IRGRP | stat.S_IXGRP |
                 stat.S_IROTH | stat.S_IXOTH)
        cmdline = ["%s/tests/%s.sh" % (self.tec.getWorkdir(), smtest)]
        outputfile = "%s/%s.txt" % (self.tec.getLogdir(), smtest)
        errfile = "%s/%s.err" % (self.tec.getLogdir(), smtest)
        for k in env.keys():
            cmdline.append("%s=%s" % (k, env[k]))
        self.commands.append(string.join(cmdline))
        ok = True
        try:
            xenrt.command("cd %s/tests && "
                          "TERM=dumb DEBUG_SETX=yes %s > %s 2> %s" %
                          (self.tec.getWorkdir(),
                           string.join(cmdline),
                           outputfile,
                           errfile),
                          timeout=46800)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Exception %s" % (str(e)))
            ok = False
            
        # Parse the output
        if os.path.exists(resfile):
            found = False
            group = None
            f = file(resfile, "r")
            gre = re.compile(r"^######## (.*)$")
            gre2 = re.compile(r"^TG: (.*)$")
            gre3 = re.compile(r"^\s*[0-9:]+\s+TG: (.*)$")
            myre = re.compile(r"^(.*)\t(PASS|FAIL)")
            riore = re.compile(r"^\s*[0-9:]+\s+(.*)")
            while True:
                line = f.readline()
                if not line:
                    break
                r = gre.search(line)
                if r:
                    group = r.group(1)
                r = gre2.search(line)
                if r:
                    group = r.group(1)
                r = gre3.search(line)
                if r:
                    group = r.group(1)
                r = myre.search(line)
                if r:
                    found = True
                    test = r.group(1)
                    r2 = riore.search(test)
                    if r2:
                        test = r2.group(1)
                    result = xenrt.RESULT_FAIL
                    if r.group(2) == "PASS":
                        result = xenrt.RESULT_PASS
                    else:
                        ok = False
                    self.testcaseResult(smtest,
                                        "%s/%s" % (group, test),
                                        result)
            if not found:
                raise xenrt.XRTError("No test results found in output file")
        else:
            raise xenrt.XRTError("No output file found")
        return ok

    def postRun(self):
        if self.iscsi:
            self.iscsi.release()
        if self.napp:
            self.napp.release()
        if self.eql:
            self.eql.release()

class TCQoSDisk(xenrt.TestCase):

    def __init__(self, tcid="TCQoSDisk"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        self.hostToClean = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        self.declareTestcase("NewDiskQoS", "prio5")
        self.declareTestcase("ionice", "prio5")
        self.declareTestcase("SetQoS", "prio2")
        self.declareTestcase("ionice", "prio2")
        self.declareTestcase("SetNoQoS", "null")
        self.declareTestcase("ionice", "null")
        self.declareTestcase("SetQoS", "prio7")
        self.declareTestcase("ionice", "prio7")
        self.declareTestcase("SetQoS", "prio3")
        self.declareTestcase("ionice", "prio3")
        self.declareTestcase("InvalidParam", "NonInteger")
        self.declareTestcase("InvalidParam", "Negative")
        self.declareTestcase("InvalidParam", "TooHigh")
            
        # Create a guest
        g = host.createGenericLinuxGuest(start=False)
        self.guestsToClean.append(g)
        self.qosguest = g

        if self.runSubcase("newDisk", (5), "NewDiskQoS", "prio5") == \
               xenrt.RESULT_PASS:
            self.runSubcase("checkUsed", (5), "ionice", "prio5")
            if self.runSubcase("setQoS", (2), "SetQoS", "prio2") == \
                   xenrt.RESULT_PASS:
                self.runSubcase("checkUsed", (2), "ionice", "prio2")
            if self.runSubcase("noQoS", (), "SetNoQoS", "null") == \
                   xenrt.RESULT_PASS:
                self.runSubcase("checkUsed", (None), "ionice", "null")
            if self.runSubcase("setQoS", (7), "SetQoS", "prio7") == \
                   xenrt.RESULT_PASS:
                self.runSubcase("checkUsed", (7), "ionice", "prio7")
            if self.runSubcase("setQoS", (3), "SetQoS", "prio3") == \
                   xenrt.RESULT_PASS:
                self.runSubcase("checkUsed", (3), "ionice", "prio3")
            
        self.runSubcase("invalid", ("x"), "InvalidParam", "NonInteger")
        self.runSubcase("invalid", ("-3"), "InvalidParam", "Negative")
        self.runSubcase("invalid", ("8"), "InvalidParam", "TooHigh")

    def newDisk(self, prio):
        g = self.qosguest
        cli = g.getCLIInstance()
        # Set the QoS on a new disk
        cli.execute("vm-disk-add",
                    "vm-name=%s disk-name=xvdc disk-qos=%u disk-size=512" %
                    (g.name, prio))
        # Check it has been applied
        disks = g.listVBDs()
        if not disks.has_key("xvdc"):
            raise xenrt.XRTFailure("Disk xvdc not present after disk-add")
        size, min_size, function, qos = disks["xvdc"]
        if not qos:
            raise xenrt.XRTFailure("No QOS set on disk xvdc")
        if qos != prio:
            raise xenrt.XRTFailure("Disk xvdc QoS %u is not what we wanted "
                                   "(%u)" % (qos, prio))

    def setQoS(self, prio):
        g = self.qosguest
        cli = g.getCLIInstance()
        # Set QoS on an existing disk
        cli.execute("vm-disk-setqos", "vm-name=%s disk-name=xvdc disk-qos=%u"
                    % (g.name, prio))
        # Check it has been applied
        disks = g.listVBDs()
        if not disks.has_key("xvdc"):
            raise xenrt.XRTFailure("Disk xvdc not present after disk-setqos")
        size, min_size, function, qos = disks["xvdc"]
        if not qos:
            raise xenrt.XRTFailure("No QOS set on disk xvdc")
        if qos != prio:
            raise xenrt.XRTFailure("Disk xvdc QoS %u is not what we wanted "
                                   "(%u)" % (qos, prio))

    def noQoS(self):
        g = self.qosguest
        cli = g.getCLIInstance()
        # Set no QoS on an existing disk
        cli.execute("vm-disk-setqos", "vm-name=%s disk-name=xvdc disk-qos=null"
                    % (g.name))
        # Check it has been applied
        disks = g.listVBDs()
        if not disks.has_key("xvdc"):
            raise xenrt.XRTFailure("Disk xvdc not present after disk-setqos")
        size, min_size, function, qos = disks["xvdc"]
        if qos:
            raise xenrt.XRTFailure("QOS is set on disk xvdc")

    def invalid(self, prio):
        g = self.qosguest
        cli = g.getCLIInstance()
        try:
            # Set QoS on an existing disk
            cli.execute("vm-disk-setqos",
                        "vm-name=%s disk-name=xvdc disk-qos=%s"
                        % (g.name, prio))
            raise xenrt.XRTFailure("Invalid QoS parameter '%s' was accepted"
                                   % (prio))
        except:
            pass

    def checkUsed(self, prio):
        g = self.qosguest
        try:
            g.start()
            d = g.getDomid()
            pid = int(g.host.execdom0(\
                "ps -A | awk '{if(/blkback.%u.xvdc/){print $1}}'" % (d)))
            actual = string.strip(g.host.execdom0("ionice -p%u" % (pid)))
            if prio == None:
                target = "none: prio 0"
            else:
                target = "best-effort: prio %u" % (prio)
            if actual != target:
                raise xenrt.XRTFailure("ionice config not expected: %s "
                                       "(should be %s)" % (actual, target))
        finally:
            g.shutdown()
                
    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)

class TCRioQoSDisk(TCQoSDisk):

    def __init__(self, tcid="TCRioQoSDisk"):
        TCQoSDisk.__init__(self, tcid)
        self.sched = "real-time" 

    def newDisk(self, prio):
        g = self.qosguest
        sruuid = g.host.getLocalSR()
        g.createDisk(sizebytes=(512*xenrt.MEGA), sruuid=sruuid, userdevice="xvdc")
        g.setDiskQoS("xvdc", sched=self.sched, value=prio)    
        # Check it has been applied.
        disks = g.listVBDs()
        if not disks.has_key("xvdc"):
            raise xenrt.XRTFailure("Disk xvdc not present after disk-add.")
        size, min_size, function, qos = disks["xvdc"]
        if not qos:
            raise xenrt.XRTFailure("No QOS set on disk xvdc.")
        if int(qos) != prio:
            raise xenrt.XRTFailure("Disk xvdc QoS %s is not what we wanted (%s)." % (qos, prio))

    def setQoS(self, prio):
        g = self.qosguest
    
        # Set QoS on an existing disk.
        g.setDiskQoS("xvdc", sched=self.sched, value=prio)

        # Check it has been applied.
        disks = g.listVBDs()
        if not disks.has_key("xvdc"):
            raise xenrt.XRTFailure("Disk xvdc not present after setting QoS.")
        size, min_size, function, qos = disks["xvdc"]
        if not qos:
            raise xenrt.XRTFailure("No QOS set on disk xvdc.")
        if int(qos) != prio:
            raise xenrt.XRTFailure("Disk xvdc QoS %s is not what we wanted (%s)." % (qos, prio))

    def noQoS(self):
        g = self.qosguest
        cli = g.getCLIInstance()

        # Set no QoS on an existing disk.
        g.setDiskQoS("xvdc")

        disks = g.listVBDs()
        if not disks.has_key("xvdc"):
            raise xenrt.XRTFailure("Disk xvdc not present after removing QoS.")
        size, min_size, function, qos = disks["xvdc"]
        if qos:
            raise xenrt.XRTFailure("No QOS set disk xvdc.")

    def invalid(self, prio):
        g = self.qosguest
        cli = g.getCLIInstance()
        try:
            # Set QoS on an existing disk.
            g.setDiskQoS("xvdc", self.sched, prio)
            raise xenrt.XRTFailure("Invalid QoS parameter '%s' was accepted" % (prio))
        except:
            pass

    def checkUsed(self, prio):
        g = self.qosguest
        try:
            g.start()
            d = g.getDomid()
            pid = int(g.host.execdom0(\
                "ps -A | awk '{if(/xb.*%u.xvdc/){print $1}}'" % (d)))
            actual = string.strip(g.host.execdom0("ionice -p%u" % (pid)))
            if prio == None:
                target = "none: prio 0"
            elif self.sched == "real-time":
                target = "realtime: prio %u" % (prio)
            else:
                target = "best-effort: prio %u" % (prio)
            if actual != target:
                raise xenrt.XRTFailure("ionice config not expected: %s "
                                       "(should be %s)" % (actual, target))
        finally:
            g.shutdown()

class TCBreakVHD(xenrt.TestCase):
    """Attempt to provoke corruption in VHDs"""

    def __init__(self, tcid="TCBreakVHD"):
        xenrt.TestCase.__init__(self, tcid)
        self.guest = None

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        duration = 3600
        distro = "debian"
        sr = None
        vcpus = None
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "machine":
                machine = l[1]
            elif l[0] == "duration":
                duration = int(l[1])
            elif l[0] == "distro":
                distro = l[1]
            elif l[0] == "sr":
                sr = l[1]
            elif l[0] == "vcpus":
                vcpus = int(l[1])
                
        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        
        self.getLogsFrom(host)

        # Create the guest
        if not sr:
            try:
                sr = host.getSRs(type="nfs")[0]
            except:
                raise xenrt.XRTError("No nfs storage repositories found!")
        else:
            # Get the UUID from the name
            srn = sr
            try:
                sr = host.parseListForParam("sr-list","name-label",srn)
            except xenrt.XRTError, e:
                raise xenrt.XRTError("Specified SR %s could not be found!" % 
                                     (srn))

        template = xenrt.lib.xenserver.getTemplate(host, distro)
        guest = host.guestFactory()(xenrt.randomGuestName(), template,
              password=xenrt.TEC().lookup("ROOT_PASSWORD_DEBIAN"))
        self.guest = guest
        guest.setMemory(256)
        if vcpus != None:
            guest.setVCPUs(vcpus)
        guest.install(host, distro=distro, sr=sr)
        
        # Add an extra VBD to it
        guest.createDisk(sizebytes=5*1000*1000*1000, sruuid=sr, userdevice="2")       

        # Assume it appears as xvdc in the guest
        device = "xvdc"       
 
        # Format and mount it, add to fstab
        guest.execguest("mkfs.ext3 /dev/%s" % (device))
        guest.execguest("mkdir /vhd")
        guest.execguest("echo \"/dev/%s		/vhd	ext3	rw,noatime	0 0\" "
                        ">> /etc/fstab" % (device))
        guest.execguest("mount /dev/%s /vhd" % (device))

        xenrt.TEC().comment("Run duration: %d seconds" % (duration))

        # Run a loop of write, reboot, read cycles for the specified duration
        stoptime = xenrt.util.timenow() + duration
        count = 0
        oldmd5 = None
        while True:
            now = xenrt.util.timenow()
            if now > stoptime:
                break          
            # Write (we tar up the rest of the dom0 filesystem, then copy it
            # a few times)
            guest.execguest("tar -cvf /vhd/filesystem.tar --exclude=/vhd/* "
                            "--exclude=/dev/* --exclude=/proc/* "
                            "--exclude=/sys/* /")
            # Grab the MD5 sum
            data = guest.execguest("md5sum /vhd/filesystem.tar")
            md5 = data.split()[0]

            # Copy it a few times
            guest.execguest("cp /vhd/filesystem.tar /vhd/filesystem2.tar")
            guest.execguest("cp /vhd/filesystem2.tar /vhd/filesystem3.tar")
            guest.execguest("cp /vhd/filesystem3.tar /vhd/filesystem4.tar")
            guest.execguest("cp /vhd/filesystem4.tar /vhd/filesystem5.tar")

            # Write out the large file
            guest.execguest("%s/remote/breakvhd.py /vhd/numbers write" % 
                            (xenrt.TEC().lookup("REMOTE_SCRIPTDIR")))

            # Reboot
            guest.reboot()

            # Verify the md5sums
            if oldmd5:
                guest.execguest("gunzip /vhd/filesystemG.tar.gz")
                data = guest.execguest("md5sum /vhd/filesystemG.tar")
                newmd5 = data.split()[0]
                if newmd5 != oldmd5:
                    raise xenrt.XRTFailure("md5sum after %d gzip procedures "
                                           "did not match!" % (count))
                guest.execguest("rm -f /vhd/filesystemG.tar")
       
                
            data = guest.execguest("md5sum /vhd/filesystem*.tar")
            datal = data.split("\n")
            for l in datal:
                ls = l.split()
                if len(ls) > 0:
                    newmd5 = ls[0]
                    if newmd5 != md5:
                        raise xenrt.XRTFailure("md5sums did not match after %d "
                                               "iterations!" % (count))

            # Make another copy and gzip it
            guest.execguest("cp /vhd/filesystem5.tar /vhd/filesystemG.tar")
            guest.execguest("gzip /vhd/filesystemG.tar")
            oldmd5 = md5
            

            # Erase
            guest.execguest("rm -f /vhd/filesystem*.tar")

            # Verify the large file
            rc = guest.execguest("%s/remote/breakvhd.py /vhd/numbers read" %
                                 (xenrt.TEC().lookup("REMOTE_SCRIPTDIR")),
                                 retval="code")
            if rc > 0:
                raise xenrt.XRTFailure("Numbers file verification failed after "
                                       "%d iterations!" % (count))

            count += 1

        # If we got here then we didn't manage to break it...
        xenrt.TEC().comment("Completed %d iterations without detecting any "
                            "corruption" % (count))

    def postRun(self):
        # Get rid of the guest
        try:
            self.guest.shutdown(again=True)
        except:
            pass
        try:
            self.guest.poll("DOWN", 120, level=xenrt.RC_ERROR)
            self.guest.uninstall()
            time.sleep(15)
        except:
            pass       

class TCMigrateVHDCheck(xenrt.TestCase):
    
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMigrateVHDCheck")
        self.semclass = "TCMigrate"
        self.guestsToClean = []

    def run(self, arglist=None):
    
        machine = "RESOURCE_HOST_0"
        maxloops = 1000
        live = "false"
        reboot = False
        target = None
        size = 8

        if arglist and len(arglist) > 0:
            machine = arglist[0]
        if arglist:
            for arg in arglist[1:]:
                l = string.split(arg, "=", 1)
                if l[0] == "maxloops":
                    maxloops = int(l[1])
                elif l[0] == "size":
                    size = int(l[1])
                elif l[0] == "live":
                    live = "true"
                elif l[0] == "reboot":
                    reboot = True
                elif l[0] == "to":
                    if l[1] != "localhost":
                        target = l[1]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Install a Linux guest
        g = host.guestFactory()(\
                xenrt.randomGuestName(), host.getTemplate("debian"),
                password=xenrt.TEC().lookup("ROOT_PASSWORD_DEBIAN"))
        self.guestsToClean.append(g)
        g.install(host, distro="debian")
        
        # Add an extra VBD to it (assume this will be /dev/xdvc, device 2)
        # Use the same SR as the first disk
        vbds = g.listVBDs()
        ds = vbds.keys()
        ds.sort()
        first = ds[0]
        u = g.getDiskVBDUUID(first)
        sruuid = g.host.getVBDSR(u)
        g.createDisk(sizebytes=size*xenrt.GIGA, sruuid=sruuid, userdevice="2")

        # Compile disktest
        g.buildProgram("disktest")
        disktest = "%s/guestprogs/disktest/disktest" % \
                   (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))


        if target:
            thost = xenrt.TEC().registry.hostGet(target)
            if not thost:
                raise xenrt.XRTError("Cannot find host %s in registry" %
                                     (target))
            self.getLogsFrom(thost)
            hostlist = [thost, g.host]
            xenrt.TEC().comment("Migrating to %s" % (thost.getName()))
        else:
            hostlist = [g.host]
            xenrt.TEC().comment("Performing localhost migrate")
        
        try:
            # Make sure there is sufficient memory on the first target
            freemem = hostlist[0].getFreeMemory()
            if freemem < g.memory:
                if xenrt.TEC().lookup("MIGRATE_NOMEM_SKIP",
                                      False,
                                      boolean=True):
                    xenrt.TEC().skip("Skipping because of insufficent free "
                                     "memory on %s (%u < %u)" %
                                     (hostlist[0].getName(),
                                      freemem,
                                      g.memory))
                    return
                else:
                    raise xenrt.XRTError("Insufficent free "
                                         "memory on %s (%u < %u)" %
                                         (hostlist[0].getName(),
                                          freemem,
                                          g.memory))
        
            # Start workloads on the guest
            writelog = string.strip(g.execguest("mktemp /tmp/writelogXXXXXX"))
            g.execguest("%s write /dev/xvdc 0 > %s 2>&1 </dev/null & " %
                        (disktest, writelog))

        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        success = 0
        try:
            terminated = False
            for i in range(maxloops):
                h = hostlist[i%len(hostlist)]
                xenrt.TEC().logverbose("Starting loop iteration %u (to %s)..."
                                       % (i, h.getName()))
                domid = g.getDomid()
                g.migrateVM(h, live=live)
                time.sleep(10)
                g.check()
                if not target:
                    # On localhost make sure we did something
                    if g.getDomid() == domid:
                        raise xenrt.XRTError("Domain ID unchanged after "
                                             "migrate.") 
                success = success + 1

                # Check if the disk writer has finished
                if g.execguest("ps ax | grep disktes[t]", retval="code") != 0:
                    terminated = True
                    break
            if not terminated:
                raise xenrt.XRTError("Reached %u iterations and disktest "
                                     "is still running" % (success))
            # Run disktest to verify the disk
            vlog = string.strip(g.execguest("mktemp /tmp/vlogXXXXXX"))
            try:
                g.execguest("%s verify /dev/xvdc 0 > %s 2>&1" % (disktest, vlog))
            finally:
                try:
                    s = g.sftpClient()
                    s.copyFrom(vlog, "%s/verifylog.txt" %
                               (self.tec.getLogdir()))
                    s.close()
                except:
                    pass
        finally:
            xenrt.TEC().comment("%u iterations successful." % (success))
            try:
                s = g.sftpClient()
                s.copyFrom(writelog, "%s/writelog.txt" %
                           (self.tec.getLogdir()))
                s.close()
            except:
                pass
        try:
            if reboot:
                g.reboot()
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError(e.reason)

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(again=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass

class TCMultipleSRs(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCMultipleSRs")
        self.guestsToClean = []
        self.SRs = []
        self.host = None
        self.cli = None

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        # By default create 20MB SRs
        size = 20
        # By default create 16 SRs
        count = 16

        if arglist:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "machine":
                    machine = l[1]
                elif l[0] == "size":
                    size = int(l[1])
                elif l[0] == "count":
                    count = int(l[1])

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        self.host = host
        self.cli = host.getCLIInstance()

        try:
            # Install a Linux guest
            g = host.createGenericLinuxGuest()
            self.guestsToClean.append(g)
    
            # Get it ready to be cloned
            g.preCloneTailor()
    
            # Make sure it's shutdown
            g.shutdown()
    
            # Set memory
            g.memset(128)
        except xenrt.XRTFailure, e:
            # A failure here is not a failure of the testcase
            raise xenrt.XRTError("Failure while installing VM: %s" % (e.reason))

        # Now create the SRs
        for i in range(count):
            try:
                self.SRs.append(host.createFileSR(size))
                self.cli.execute("sr-list")
            except xenrt.XRTException, e:
                raise xenrt.XRTFailure("Exception creating SR %d/%d: %s" % 
                                       (i+1,count,e.reason))

        # Clone an appropriate number of guests, each one has 2 default VBDs, 
        # so can put 5 of mine onto each (don't want more than 7 per guest)
        guestsNeeded = count / 5
        if count % 5 > 0:
            guestsNeeded += 1

        # We already have one guest (the one we're going to clone), so how many
        # do we need to clone now
        for i in range(guestsNeeded - 1):
            try:
                self.guestsToClean.append(g.cloneVM())  
            except xenrt.XRTException, e:
                raise xenrt.XRTError("Exception cloning VM %d/%d: %s" %
                                     (i+1,guestsNeeded-1,e.reason))

        # Now we should have the right number of guests, let's start adding to
        # them...
        guest = 0
        gcount = 0
        for sr in self.SRs:
            self.guestsToClean[guest].createDisk(sizebytes=(size*xenrt.MEGA), 
                                                 sruuid=sr, userdevice=(gcount + 2))
            gcount += 1
            if gcount == 5:
                guest += 1
                gcount = 0

        # Now let's try and start all the guests
        count = 1
        for guest in self.guestsToClean:
            try:
                guest.start()
            except xenrt.XRTException, e:
                raise xenrt.XRTFailure("Exception starting VM %d/%d: %s" %
                                       (count,len(self.guestsToClean),e.reason))
            count += 1

        # They all started, so let's shut them down again
        count = 1
        for guest in self.guestsToClean:
            try:
                guest.shutdown()
            except xenrt.XRTException, e:
                raise xenrt.XRTFailure("Exception stopping VM %d/%d: %s" %
                                       (count,len(self.guestsToClean),e.reason))

        # Done!

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            try:
                g.poll("DOWN", 120, level=xenrt.RC_ERROR)
                g.uninstall()
                time.sleep(15)
            except:
                pass

        for sr in self.SRs:
            try:
                self.host.destroyFileSR(sr)
                self.cli.execute("sr-list")
            except:
                xenrt.TEC().warning("Exception while destroying SR %s" % (sr))

class TCVDICopy(xenrt.TestCase):
    """Test the vdi-copy CLI command"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCVDICopy")

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        loops = 10
        sr = None
        srtype = "lvm"

        if arglist:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "machine":
                    machine = l[1]
                elif l[0] == "loops":
                    loops = int(l[1])
                elif l[0] == "sr":
                    sr = l[1]
                elif l[0] == "srtype":
                    srtype = l[1]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        cli = host.getCLIInstance()

        # Find an SR to use
        if not sr:
            try:
                sr = host.getSRs(type=srtype)[0]
            except:
                raise xenrt.XRTError("No %s storage repositories found!" % 
                                     (srtype))
        else:
            # Get the UUID from the name
            srn = sr
            try:
                sr = host.parseListForParam("sr-list","name-label",srn)
            except xenrt.XRTError, e:
                raise xenrt.XRTError("Specified SR %s could not be found!" %
                                     (srn))

        success = 0

        try:
            for i in range(loops):
                xenrt.TEC().logverbose("Starting loop iteration %u..." % (i))
                
                # Create 4 VDIs
                vdis = []
                for i in range(4):
                    args = []
                    args.append("sr-uuid=%s" % (sr))
                    args.append("name-label=\"XenRT TCVDICopy VDI %d\"" % (i))
                    args.append("type=\"user\"")
                    args.append("virtual-size=%d" % (2 * xenrt.GIGA))
                    vdis.append(cli.execute("vdi-create",string.join(args),
                                            strip=True))

                # Attach them to dom0
                vbds = []
                devs = []
                for i in range(4):
                    args = []
                    args.append("vm-uuid=%s" % (host.getMyDomain0UUID()))
                    args.append("device=autodetect")
                    args.append("vdi-uuid=%s" % (vdis[i]))
                    vbds.append(cli.execute("vbd-create",string.join(args),
                                                strip=True))
                    cli.execute("vbd-plug","uuid=%s" % (vbds[i]))
                    devs.append(host.genParamGet("vbd",vbds[i],"device"))

                # Put known patterns on them
                for i in range(4):
                    host.execdom0("%s/remote/patterns.py /dev/%s %d write %d" %
                                  (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                                   devs[i],2*xenrt.GIGA,i))

                # Wait a short time to make sure they get released in dom0
                time.sleep(60)

                # Detach from dom0
                for vbd in vbds:
                    cli.execute("vbd-unplug","uuid=%s" % (vbd))
                    cli.execute("vbd-destroy","uuid=%s" % (vbd))

                # Copy them and delete the originals
                newvdis = []
                for vdi in vdis:
                    args = []
                    args.append("uuid=%s" % (vdi))
                    args.append("sr-uuid=%s" % (sr))
                    newvdis.append(cli.execute("vdi-copy",string.join(args),
                                               strip=True))
                    cli.execute("vdi-destroy","uuid=%s" % (vdi))

                # Attach the copies to dom0
                vbds = []
                devs = []
                for i in range(4):
                    args = []
                    args.append("vm-uuid=%s" % (host.getMyDomain0UUID()))
                    args.append("device=autodetect")
                    args.append("vdi-uuid=%s" % (newvdis[i]))
                    vbds.append(cli.execute("vbd-create",string.join(args),
                                                strip=True))
                    cli.execute("vbd-plug","uuid=%s" % (vbds[i]))
                    devs.append(host.genParamGet("vbd",vbds[i],"device"))

                # Check the patterns are correct
                for i in range(4):
                    rc = host.execdom0("%s/remote/patterns.py /dev/%s %d read %d" %
                                       (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                                        devs[i],2*xenrt.GIGA,i),retval="code")
                    if rc > 0:
                        raise xenrt.XRTFailure("VDI patterns do not match!")

                # Wait a short time to make sure they get released in dom0
                time.sleep(60)

                # Detach and delete the copies
                for vbd in vbds:
                    cli.execute("vbd-unplug","uuid=%s" % (vbd))
                    cli.execute("vbd-destroy","uuid=%s" % (vbd))
                for vdi in newvdis:
                    cli.execute("vdi-destroy","uuid=%s" % (vdi))

                success += 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" % (success, loops))

class TCVirtualCDs(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCVirtualCDs")
        self.guest = None
        self.cdname = None
        self.hvm = None

    def run(self, arglist=None):
        loops = 10

        gname = None 
       
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "loops":
                loops = int(l[1])
            elif l[0] == "guest":
                gname = l[1]
            elif l[0] == "cd":
                self.cdname = l[1]
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0]
        if not gname:
            raise xenrt.XRTError("You must specify an existing guest")

        g = self.getGuest(gname)
        self.guest = g
        if not g:
            raise xenrt.XRTError("Could not find guest %s in registry" %
                                (gname))

        host = g.host
        self.getLogsFrom(host)
        cli = host.getCLIInstance()

        # Make sure the guest is running (we need it to be to determine
        # HVM status)
        if g.getState() == "DOWN":
            g.start()

        # Is this an HVM guest, if so we can't do anything 'hot'
        if g.getDomainType() == "hvm":
            hvm = True
            g.shutdown()
        else:
            hvm = False
        self.hvm = hvm    

        guuid = g.getUUID()
        if not self.cdname:
            # Don't use xs-tools.iso, we don't want something that autoruns
            # in windows!
            self.cdname = "rhel4.4-updates.img.iso"

        # Find the md5sum
        real_md5 = host.execdom0("md5sum /opt/xensource/packages/iso/%s" % 
                                 (self.cdname))
        self.real_md5 = real_md5.split()[0]

        # Remove any existing CD devices
        try:
            self.removeAllDrives(not hvm)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Failure while removing existing CD devices")
    
        # Start the loop
        success = 0
        try:
            for i in range(loops):
                # Add a CD drive
                args = []
                args.append("uuid=%s" % (guuid))
                args.append("cd-name=\"%s\"" % (self.cdname))
                args.append("device=autodetect")
                cli.execute("vm-cd-add",string.join(args))
                if hvm:
                    g.start()
                self.checkCD(1)

                # eject/insert 20 times
                for j in range(20):
                    args = []
                    args.append("uuid=%s" % (guuid))
                    cli.execute("vm-cd-eject",string.join(args))
                    self.checkCD(1,ejected=True)
                    args = []
                    args.append("uuid=%s" % (guuid))
                    args.append("cd-name=\"%s\"" % (self.cdname))
                    cli.execute("vm-cd-insert",string.join(args))
                    self.checkCD(1)

                # Add more CD drives such that we have 5 (or 3 if windows)
                if hvm:
                    g.shutdown()
                args = []
                args.append("uuid=%s" % (guuid))
                args.append("cd-name=\"%s\"" % (self.cdname))
                args.append("device=autodetect")
                cli.execute("vm-cd-add",string.join(args))
                cli.execute("vm-cd-add",string.join(args))
                if not g.windows:
                    cli.execute("vm-cd-add",string.join(args))
                    cli.execute("vm-cd-add",string.join(args))
                if hvm:
                    g.start()
                if g.windows:
                    self.checkCD(3)
                else:
                    self.checkCD(5)

                # Remove the CD drives
                g.shutdown()
                args = []
                args.append("uuid=%s" % (guuid))
                args.append("cd-name=\"%s\"" % (self.cdname))
                cli.execute("vm-cd-remove",string.join(args))
                cli.execute("vm-cd-remove",string.join(args))
                cli.execute("vm-cd-remove",string.join(args))
                if not g.windows:
                    cli.execute("vm-cd-remove",string.join(args))
                    cli.execute("vm-cd-remove",string.join(args))
                if not hvm:
                    g.start()
                success += 1
                
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" % (success, loops))

    def checkCD(self,numDrives,ejected=False):
        # Check that there are numDrives, and that they all exist

        # First do a vm-cd-list and check that it shows that many
        g = self.guest
        host = g.host
        cli = host.getCLIInstance()
        vbds = host.minimalList("vm-cd-list",args="uuid=%s vdi-params=None" % 
                                                  (g.getUUID()))
        actualNumDrives = len(vbds)
        if numDrives != actualNumDrives:
            raise xenrt.XRTFailure("Expecting %u drives, found %u" % 
                                   (numDrives,actualNumDrives))
        g = self.guest
        if g.windows:
            # Use XML-RPC
            # Get the output of "list volumes" in diskpart
            g.xmlrpcWriteFile("C:\\listvol.txt","list volume")
            vols = g.xmlrpcExec("diskpart /s c:\\listvol.txt",returndata=True)

            # Match it to find drive letters of CD/DVD-ROM drives
            lines = vols.split("\n")
            drives = []
            for line in lines:
                m = re.match("\s*Volume \d\s*([A-Z]).*(CD|DVD)-ROM",line)
                if m:
                    drives.append(m.group(1))

            # Check the right number are there
            if len(drives) != numDrives:
                raise xenrt.XRTFailure("Expecting %u drives, found %u" %
                                       (numDrives,len(drives)))

            # Go through each one, md5sum it TODO
        else:
            # Use SSH
            if self.hvm:
                # Different distros will give CD drives different names, so we
                # can't easily verify in this situation
                pass
            else:
                if not ejected:
                    for vbd in vbds:
                        # Find out the device
                        dev = host.genParamGet("vbd",vbd,"device")
                        # See if it's there
                        if g.execguest("ls /dev/%s" % (dev),retval="code") > 0:
                            raise xenrt.XRTFailure("Device %s not present on "
                                                   "guest" % (dev))

                    # Check the expected contents are there
                    md5 = g.execguest("md5sum /dev/%s" % (dev))
                    md5 = md5.split()[0]
                    if md5 != self.real_md5:
                        raise xenrt.XRTFailure("Contents of device %s are not "
                                               "as expected" % (dev))

    def postRun(self):
        # Clean up...
        try:
            self.guest.shutdown()
            self.removeAllDrives(unplug=False)
        except:
            pass

    def removeAllDrives(self,unplug=True):
        host = self.guest.host
        cd_vbds = host.minimalList("vbd-list",args="vm-uuid=%s type=CD" % 
                                                   (self.guest.getUUID()))
        cli = host.getCLIInstance()

        for vbd in cd_vbds:
            if unplug:
                if host.genParamGet("vbd",vbd,"currently-attached") == "true":
                    cli.execute("vbd-unplug", "uuid=%s" % (vbd))
            cli.execute("vbd-destroy", "uuid=%s" % (vbd))

class TCremoveVGsAndPVs(xenrt.TestCase):
    """Remove all VGs and PVs from the host"""

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCremoveVGsAndPVs")

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"

        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        
        # We assume we're being run on a host with no VMs running!

        # Remove any VGs

        vgs = host.execdom0("vgdisplay -s 2>/dev/null").split("\n")
        for vg in vgs:
            vgsplit = vg.split()
            if len(vgsplit) < 5:
                continue
            vgpath = vgsplit[0].replace("\"","")
            xenrt.TEC().comment("Removing VG %s" % (vgpath))
            host.execdom0("vgremove /dev/%s" % (vgpath))

        # Now remove any PVs

        pvs = host.execdom0("pvdisplay -s").split("\n")
        for pv in pvs:
            pvsplit = pv.split()
            if len(pvsplit) < 5:
                continue
            pvpath = pvsplit[1].replace("\"","")
            xenrt.TEC().comment("Removing PV %s" % (pvpath))
            host.execdom0("pvremove %s" % (pvpath))

