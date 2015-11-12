#
# XenRT: Test harness for Xen and the XenServer product family
#
# Multipathing tests
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#
import socket, re, string, time, traceback, sys, random, copy, threading, os.path
import xenrt, xenrt.lib.xenserver, testcases, testcases.xenserver.tc.vhd, testcases.xenserver.tc.ha
from xenrt.lazylog import step, comment, log

#############################################################################
# iSCSI

class _SoftwareMultipath(xenrt.TestCase):
    """Base class for software multipath tests"""
    MULTIPATHING = True # Do we enable multipathing on the host
    MULTITARGET = True  # Do we make the target multihomed
    TARGETONSEC = False # Should the target be on NSEC
    SAMESUBNET = False  # Should the target have two interfaces on the same net
    EXTRA_INTFS = 0     # Number of extra (private) interfaces to create
    SETUPSECNIC = False # Whether to explicitly set up a secondary NIC
    DEFSCHED = None
    SRSIZE = 1024 # in MiB

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.currentMultipathing = self.MULTIPATHING
        self.pathBlocked = False
        self.lun = None

    def prepare(self, arglist=None):
        self.sruuids = []
        # in thin LVHD, local allocator requires 1GiB per allocation,
        # which happens multiple times per each host.
        if self.tcsku == "thin":
            self.SRSIZE = 4096 # in MiB

        # Set up a multihomed target VM on one host. Add a second interface
        # on the second logical network.
        self.targethost = self.getHost("RESOURCE_HOST_0")
        if (self.MULTITARGET and not self.SAMESUBNET) or self.TARGETONSEC:
            nsecaids = self.targethost.listSecondaryNICs("NSEC")
            if len(nsecaids) == 0:
                raise xenrt.XRTError("Could not find a NSEC interface on target"
                                     " host")
        if self.TARGETONSEC:
            bridge = self.targethost.getBridgeWithMapping(nsecaids[0])
        else:
            bridge = self.targethost.getPrimaryBridge()        
        self.targetguest = self.targethost.createGenericLinuxGuest(bridge=bridge)
        ethIndex = 1
        if self.MULTITARGET:
            if self.SAMESUBNET:
                bridge1 = self.targethost.getPrimaryBridge()
            else:
                bridge1 = self.targethost.getBridgeWithMapping(nsecaids[0])
            self.targetguest.createVIF(eth="eth1", bridge=bridge1)
            self.targetguest.plugVIF("eth1")
            time.sleep(5)
            self.targetguest.execguest("echo 'auto eth1' >> "
                                       "/etc/network/interfaces")
            self.targetguest.execguest("echo 'iface eth1 inet dhcp' >> "
                                       "/etc/network/interfaces")
            self.targetguest.execguest("echo 'post-up route del -net default "
                                       "dev eth1' >> /etc/network/interfaces")
            self.targetguest.execguest("ifup eth1")
            ethIndex = 2

        for i in range(self.EXTRA_INTFS):
            # Add an extra interface to the guest on a private bridge
            self.targetguest.createVIF(eth="eth%u" % (i + ethIndex))
            self.targetguest.plugVIF("eth%u" % (i + ethIndex))
            time.sleep(5)
            self.targetguest.execguest("echo 'auto eth%u' >> "
                                       "/etc/network/interfaces" % 
                                       (i + ethIndex))
            self.targetguest.execguest("echo 'iface eth%u inet static' >> "
                                       "/etc/network/interfaces" % 
                                       (i + ethIndex))
            self.targetguest.execguest("echo 'address 192.168.%u.1' >> "
                                       "/etc/network/interfaces" % (i + 150))
            self.targetguest.execguest("echo 'netmask 255.255.255.0' >> "
                                       "/etc/network/interfaces")
            self.targetguest.execguest("ifup eth%u" % (i + ethIndex))

        self.uninstallOnCleanup(self.targetguest)
        self.getLogsFrom(self.targetguest)
        self.targetiqn = self.targetguest.installLinuxISCSITarget()
        self.targetguest.createISCSITargetLun(0, self.SRSIZE)

        # Clean up another host to use in the test
        self.host0 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()

        if (self.MULTITARGET and not self.SAMESUBNET) or self.SETUPSECNIC:
            # Set up an IP address on the NSEC interface
            h0nsecaids = self.host0.listSecondaryNICs("NSEC")
            if len(h0nsecaids) == 0:
                raise xenrt.XRTError("Could not find a NSEC interface on host")
            self.host0.setIPAddressOnSecondaryInterface(h0nsecaids[0])

    def run(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        # Set up the SR on the host
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host0,
                                                             "TC7835", thinprov)
        self.lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" %
                                      (self.targetiqn,
                                       self.targetguest.getIP()))
        sr.create(self.lun, subtype="lvm", findSCSIID=True, multipathing=self.MULTIPATHING)
        sruuid = sr.uuid
        self.sruuids.append(sruuid)
        lunid = 0
        time.sleep(5) # CA-22523
        self.checkMultipathConfig(self.host0, sruuid, lunid)

        # Create a 256M VDI on the SR
        cli = self.host0.getCLIInstance()
        args = []
        args.append("name-label='XenRT Test VDI on %s'" % (sruuid))
        args.append("sr-uuid=%s" % (sruuid))
        args.append("virtual-size=268435456") # 256M
        args.append("type=user")
        vdi = cli.execute("vdi-create", string.join(args), strip=True)

        # Attach vdi to dom0, and create a filesystem
        args = []
        args.append("vm-uuid=%s" % (self.host0.getMyDomain0UUID()))
        args.append("vdi-uuid=%s" % (vdi))
        args.append("device=autodetect")
        vbd = cli.execute("vbd-create", string.join(args), strip=True)
        cli.execute("vbd-plug","uuid=%s" % (vbd))
        time.sleep(5)
        dev = self.host0.genParamGet("vbd", vbd, "device")
        self.host0.execdom0("mkfs.ext3 /dev/%s" % (dev))
        self.host0.execdom0("mkdir -p /tmp/xenrt_multipath")
        self.host0.execdom0("mount /dev/%s /tmp/xenrt_multipath" % (dev))
        self.host0.execdom0("umount /tmp/xenrt_multipath")        

        # Now delete it
        cli.execute("vbd-unplug", "uuid=%s" % (vbd))
        cli.execute("vbd-destroy", "uuid=%s" % (vbd))
        cli.execute("vdi-destroy","uuid=%s" % (vdi))

    def checkMultipathConfig(self, host, sruuid, lunid):
        # Check the host has multipathing correctly set up

        pbd = host.parseListForUUID("pbd-list",
                                    "sr-uuid",
                                    sruuid,
                                    "host-uuid=%s" % (host.getMyHostUUID()))
        scsiid = host.genParamGet("pbd", pbd, "device-config", "SCSIid")
        mpdevs = host.getMultipathInfo()

        if not self.currentMultipathing:
            # Config should be disabled
            # We don't do symlink check from Cowley onwards
            if not isinstance(host, xenrt.lib.xenserver.MNRHost) or host.productVersion == 'MNR':
                cf = host.execdom0("readlink /etc/multipath.conf")
                if os.path.basename(cf.strip()) != "multipath-disabled.conf":
                    raise xenrt.XRTFailure("Multipath daemon not disabled when "
                                           "multipathing turned off")

            # Check that multipath -l gives only local disks
            if mpdevs.has_key(scsiid):
                raise xenrt.XRTFailure("Multipath information found when "
                                       "multipathing disabled")

            # Everything is as expected
            return

        pid = host.execdom0("pidof multipathd || true").strip()
        if pid == "":
            raise xenrt.XRTFailure("multipathd not running")

        if not mpdevs.has_key(scsiid):
            raise xenrt.XRTFailure("Could not find SCSI ID in multipath status",
                                   "SCSIid %s" % (scsiid))
        if self.MULTITARGET and not self.pathBlocked:
            pathCount = 2
        else:
            pathCount = 1
        if len(mpdevs[scsiid]) != pathCount:
            raise xenrt.XRTFailure("Incorrect number of paths found",
                                   "Expected %u got %u (%s)" %
                                   (pathCount,len(mpdevs[scsiid]),
                                    string.join(mpdevs[scsiid])))
        for dev in mpdevs[scsiid]:
            id = host.getSCSIID(dev)
            if id != scsiid:
                raise xenrt.XRTFailure("Multipath SCSI ID mismatch",
                                       "Expecting %s but %s was %s" %
                                       (scsiid, dev, id))
        targets = host.execdom0("ls /dev/iscsi/%s" % (self.targetiqn)).split()
        if len(targets) != pathCount:
            raise xenrt.XRTFailure("Incorrect number of targets found",
                                   "Expected %u got %u (%s)" %
                                   (pathCount,len(targets),
                                    string.join(targets)))
        for target in targets:
            dev = host.execdom0("readlink -f /dev/iscsi/%s/%s/LUN%u"
                                % (self.targetiqn, target, lunid)).strip()
            if not os.path.basename(dev) in mpdevs[scsiid]:
                raise xenrt.XRTFailure("iSCSI device not found in multipath",
                                       "%s LUN %u is %s, not in %s" %
                                       (target,
                                        lunid,
                                        dev,
                                        string.join(mpdevs[scsiid])))

        # Check the PBD other-config data
        if self.MULTITARGET and not self.pathBlocked:
            maxPaths = 2
        else:
            maxPaths = 1

        try:
            counts = host.getMultipathCounts(pbd, scsiid)   
        except:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Couldn't retrieve multipath counts from PBD"
                                   " other-config")
        # Deal with the fact we may have 4 entries in the list from older versions
        if isinstance(host, xenrt.lib.xenserver.Host) and host.productVersion == 'Orlando':
            counts = [counts[0], counts[1]]
        if counts != [pathCount, maxPaths]:
            raise xenrt.XRTFailure("Multipath count from PBD "
                                   "other-config does not match expectations",
                                   "Expecting %s got %s" %
                                   ([pathCount, maxPaths], counts))

        # Check the iSCSI session count
        if isinstance(host, xenrt.lib.xenserver.Host) and not host.productVersion == 'Orlando':
            try:
                isessions = int(host.genParamGet("pbd", pbd, "other-config", "iscsi_sessions"))
            except:
                traceback.print_exc(file=sys.stderr)
                raise xenrt.XRTFailure("Couldn't retrieve iscsi_sessions "
                                       "count from PBD other-config")
    
            if isessions != maxPaths:
                raise xenrt.XRTFailure("iSCSI session count from PBD "
                                       "other-config is not as expected",
                                       "Expecting %u got %u" %
                                       (maxPaths, isessions))

        if self.DEFSCHED:
            # Check the correct default scheduler has been set
            errors = 0
            for dev in mpdevs[scsiid]:
                data = host.execdom0("cat /sys/block/%s/queue/scheduler" %
                                     (dev))
                if not re.search(r"\[%s\]" % (self.DEFSCHED), data):
                    xenrt.TEC().logverbose("Device %s does not have the "
                                           "expected scheduler (%s): %s" %
                                           (dev, self.DEFSCHED, data.strip()))
                    errors = errors + 1
            if errors > 0:
                raise xenrt.XRTFailure("%u/%u paths do not have correct block "
                                       "scheduler set" % (errors,
                                                          len(mpdevs[scsiid])))

    def postRun(self):
        # Cleanup
        for sruuid in self.sruuids:
            # We created an SR, lets try and forget it
            try:
                self.host0.forgetSR(sruuid)
            except:
                xenrt.TEC().warning("Exception while forgetting SR on host")
        if self.lun:
            self.lun.release()

class TC7833(_SoftwareMultipath):
    """iSCSI SR creation on a non-multihomed iSCSI target with host multipathing
       enabled"""
    MULTITARGET = False

class TC7834(_SoftwareMultipath):
    """iSCSI SR creation on a non-multihomed iSCSI target on a non-local subnet
       with host multipathing enabled"""
    MULTITARGET = False
    TARGETONSEC = True

class TC7835(_SoftwareMultipath):
    """iSCSI SR creation on a multihomed iSCSI target using multipathing"""
    pass

class TC7836(_SoftwareMultipath):
    """iSCSI SR creation on a multihomed iSCSI target without multipathing"""
    MULTIPATHING = False

class TC7837(_SoftwareMultipath):
    """iSCSI SR creation on a multihomed (but on the same subnet) iSCSI target
       using multipathing"""
    SAMESUBNET = True

class TC7838(_SoftwareMultipath):
    """iSCSI SR creation on a multihomed iSCSI target with one path
       unreachable"""
    MULTITARGET = False
    EXTRA_INTFS = 1

class TC7839(_SoftwareMultipath):
    """iSCSI SR creation on a multihomed iSCSI target with 4 interfaces"""
    # The default 2 interfaces will be reachable, the additional 2 here won't be
    EXTRA_INTFS = 2

class TC8370(_SoftwareMultipath):
    """All block devices in a freshly created multipathed iSCSI SR should have the default scheduler set"""
    DEFSCHED = "noop"
    
class _TC8012(_SoftwareMultipath):
    """Base class for TC-8012 tests: iSCSI multipath forgetting/destruction"""
    DESTROY = True # True = sr-destroy, False = sr-forget
    BLOCK = None # Which paths to block: None = neither, "PRI" = Primary, 
                 # "SEC" = Secondary

    def run(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        # Set up the SR on the host
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host0,
                                                             "TC8012", thinprov)
        self.lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" %
                                      (self.targetiqn,
                                       self.targetguest.getIP()))
        sr.create(self.lun, subtype="lvm", findSCSIID=True, multipathing=self.MULTIPATHING)
        sruuid = sr.uuid
        self.sruuids.append(sruuid)
        lunid = 0
        time.sleep(5) # CA-22523

        self.checkMultipathConfig(self.host0, sruuid, lunid)

        priIP = self.targetguest.getIP()
        secIP = None
        if self.MULTITARGET:
            vifs = self.targetguest.getVIFs()
            # We assume its eth1
            secIP = vifs['eth1'][1]

        # Are we meant to block any paths
        if self.BLOCK:
            inOrOut = random.choice(["INPUT","OUTPUT"])
            sourceOrDest = (inOrOut == "INPUT") and "s" or "d"
            if self.BLOCK == "PRI":
                xenrt.TEC().comment("Blocking primary path")
                self.host0.execdom0("iptables -I %s -%s %s -j DROP" % 
                                    (inOrOut,sourceOrDest,priIP))
            elif self.BLOCK == "SEC":
                if not self.MULTITARGET:
                    raise xenrt.XRTError("Cannot block secondary path when "
                                         "target is single homed")
                xenrt.TEC().comment("Blocking secondary path")
                self.host0.execdom0("iptables -I %s -%s %s -j DROP" %
                                    (inOrOut,sourceOrDest,secIP))
            else:
                raise xenrt.XRTError("Unknown BLOCK value %s" % (self.BLOCK))

            # Wait for 10 seconds for the block to 'settle'
            time.sleep(10)

        # Are we destroying or forgetting?
        if self.DESTROY:
            # Destroy
            self.host0.destroySR(sruuid)
        else:
            # Forget
            self.host0.forgetSR(sruuid)

    def postRun(self):
        if self.lun:
            self.lun.release()

class TC8014(_TC8012):
    """iSCSI SR destruction on a non-multihomed iSCSI target"""
    MULTITARGET = False

class TC8015(_TC8012):
    """iSCSI SR destruction on a multihomed iSCSI target"""
    pass

class TC8016(_TC8012):
    """iSCSI SR destruction on a multihomed iSCSI target with primary path
       degraded"""
    BLOCK = "PRI"

class TC8017(_TC8012):
    """iSCSI SR destruction on a multihomed iSCSI target with secondary path
       degraded"""
    BLOCK = "SEC"

class TC8018(TC8014):
    """iSCSI SR forgetting on a non-multihomed iSCSI target"""
    DESTROY = False

class TC8019(TC8015):
    """iSCSI SR forgetting on a multihomed iSCSI target"""
    DESTROY = False

class TC8020(TC8016):
    """iSCSI SR forgetting on a multihomed iSCSI target with primary path
       degraded"""
    DESTROY = False

class TC8021(TC8017):
    """iSCSI SR forgetting on a multihomed iSCSI target with secondary path
       degraded"""
    DESTROY = False


class _TC8013(_SoftwareMultipath):
    """Base class for TC-8013 tests: iSCSI multipath changes"""
    MULTIPATHING = False # Whether to start off multipathed or not
    BLOCK = None # Block none, PRI or SEC path
    MULTITARGET = True # Always want a multihomed target
    SETUPSECNIC = True # Always set up the secondary NIC on the host

    def run(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        step('Set up the SR on the host')
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host0,
                                                             "TC8013", thinprov)
        self.lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" %
                                      (self.targetiqn,
                                       self.targetguest.getIP()))
        if self.MULTIPATHING:
            srmp = True
        else:
            self.host0.disableMultipathing()
            srmp = None
        sr.create(self.lun, subtype="lvm", findSCSIID=True, multipathing=srmp)
        sruuid = sr.uuid
        self.sruuids.append(sruuid)
        lunid = 0
        time.sleep(5) # CA-22523

        self.checkMultipathConfig(self.host0, sruuid, lunid)

        priIP = self.targetguest.getIP()
        vifs = self.targetguest.getVIFs()
        # We assume its eth1
        secIP = vifs['eth1'][1]

        # Are we meant to block any paths?
        if self.BLOCK:
            inOrOut = random.choice(["INPUT","OUTPUT"])
            sourceOrDest = (inOrOut == "INPUT") and "s" or "d"
            if self.BLOCK == "PRI":
                step('Block primary path')
                xenrt.TEC().comment("Blocking primary path")
                self.host0.execdom0("iptables -I %s -%s %s -j DROP" %
                                    (inOrOut,sourceOrDest,priIP))
                self.pathBlocked = True
            elif self.BLOCK == "SEC":
                step('Block secondary path')
                xenrt.TEC().comment("Blocking secondary path")
                self.host0.execdom0("iptables -I %s -%s %s -j DROP" %
                                    (inOrOut,sourceOrDest,secIP))
                self.pathBlocked = True
            else:
                raise xenrt.XRTError("Unknown BLOCK value %s" % (self.BLOCK))

            # Wait for 10 seconds for the block to 'settle'
            time.sleep(10)

        # Re-plug PBDs
        pbds = sr.getPBDs()
        # We only expect one PBD
        pbd = pbds.keys()[0]
        cli = self.host0.getCLIInstance()
        step('Unplug the PBD')
        cli.execute("pbd-unplug","uuid=%s" % (pbd))

        # What are we changing to?
        if self.MULTIPATHING:
            step('Disable multipathing')
            self.host0.disableMultipathing()
            self.currentMultipathing = False
        else:
            step('Enable multipathing')
            self.host0.enableMultipathing()
            self.currentMultipathing = True

        step('Plug back the PBD')
        cli.execute("pbd-plug","uuid=%s" % (pbd))

        time.sleep(5) # CA-22523

        step('Check Multipathing configuration')
        self.checkMultipathConfig(self.host0, sruuid, lunid)

class TC8025(_TC8013):
    """Enable multipathing with pre-existing SR on multihomed target with both
       paths reachable"""
    pass

class TC8026(_TC8013):
    """Enable multipathing with pre-existing SR on multihomed target with new
       path unreachable"""
    BLOCK = "SEC"

class TC8027(_TC8013):
    """Disable multipathing with pre-existing SR on multihomed target with both
       paths reachable"""
    MULTIPATHING = True

class TC10614(_TC8013):
    """After disabling iSCSI multipathing the PBD other-config multipath entries should be deleted on PBD.unplug"""
    MULTIPATHING = True

    def run(self, arglist=None):
        _TC8013.run(self, arglist)
        for sruuid in self.sruuids:
            pbds = self.host0.minimalList("pbd-list",
                                          args="sr-uuid=%s" % (sruuid))
            for pbd in pbds:
                oc = self.host0.genParamGet("pbd", pbd, "other-config")
                if "multipathed" in oc:
                    raise xenrt.XRTFailure("multipathed key still recorded "
                                           "for PBD after multipath disabled")
                if "mpath" in oc:
                    raise xenrt.XRTFailure("mpath-* key still recorded "
                                           "for PBD after multipath disabled")

class TC8028(_TC8013):
    """Disable multipathing with pre-existing SR on multihomed target with
       primary path unreachable"""
    MULTIPATHING = True
    BLOCK = "PRI"

class TC8029(_TC8013):
    """Disable multipathing with pre-existing SR on multihomed target with
       secondary path unreachable"""
    MULTIPATHING = True
    BLOCK = "SEC"

class TC8031(xenrt.TestCase):
    """Join non-multipathed slave to non-multipathed master with an SR on a
       multihomed iSCSI target"""
    MULTIMASTER = False
    MULTISLAVE = False
    MPP_RDAC = False    # Do we enable MPP-RDAC

    def prepare(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        # Get host objects
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")

        # Reset master+slave to fresh install
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Create the pool object
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)

        if not self.MPP_RDAC:
            self.targethost = self.getHost("RESOURCE_HOST_2")

            nsecaids = self.targethost.listSecondaryNICs("NSEC")
            if len(nsecaids) == 0:
                raise xenrt.XRTError("Could not find a NSEC interface on target"
                                     " host")
                                     
            # Prepare a multihomed iSCSI target VM
            self.targetguest = self.targethost.createGenericLinuxGuest()
            bridge1 = self.targethost.getBridgeWithMapping(nsecaids[0])
            self.targetguest.createVIF(eth="eth1", bridge=bridge1, plug=True)
            time.sleep(5)
            self.targetguest.execguest("echo 'auto eth1' >> "
                                       "/etc/network/interfaces")
            self.targetguest.execguest("echo 'iface eth1 inet dhcp' >> "
                                       "/etc/network/interfaces")
            self.targetguest.execguest("echo 'post-up route del -net default "
                                       "dev eth1' >> /etc/network/interfaces")
            self.targetguest.execguest("ifup eth1")
            self.uninstallOnCleanup(self.targetguest)
            self.getLogsFrom(self.targetguest)
            self.initiator = "xenrt-test"
            self.targetiqn = self.targetguest.installLinuxISCSITarget()
            self.targetguest.createISCSITargetLun(0, 1024) 
            self.targetip = self.targetguest.getIP()
            self.lunid = 0
            self.numpaths = 2
        else:
            self.numpaths = 4

        # Set up NICs on master and slave
        h0nsecaids = self.host0.listSecondaryNICs("NSEC")
        if len(h0nsecaids) == 0:
            raise xenrt.XRTError("Could not find a NSEC interface on host %s" %
                                 (self.host0.getName()))
        self.host0.setIPAddressOnSecondaryInterface(h0nsecaids[0])
        h1nsecaids = self.host1.listSecondaryNICs("NSEC")
        if len(h1nsecaids) == 0:
            raise xenrt.XRTError("Could not find a NSEC interface on host %s" %
                                 (self.host1.getName()))
        self.host1.setIPAddressOnSecondaryInterface(h1nsecaids[0])

        # Enable multipathing where appropriate
        if self.MULTIMASTER:
            self.host0.enableMultipathing(mpp_rdac=self.MPP_RDAC)
        if self.MULTISLAVE:
            self.host1.enableMultipathing(mpp_rdac=self.MPP_RDAC)
            
        # Setup iSCSI SR on master 
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host0,
                                                             "TC8031", thinprov)
        if not self.MPP_RDAC:
            self.lun = xenrt.ISCSILunSpecified("%s/%s/%s" %
                                          (self.initiator,
                                           self.targetiqn,
                                           self.targetip))
        else:
            self.lun = xenrt.ISCSILun(minsize=50,mpprdac=True)
            self.initiator = self.lun.getInitiatorName()
            self.targetiqn = self.lun.getTargetName()
            self.targetip = self.lun.getServer()
            self.lunid = self.lun.getID()

        self.sr.create(self.lun, subtype="lvm", findSCSIID=(not self.MPP_RDAC), mpp_rdac=self.MPP_RDAC)

        self.sr.prepareSlave(self.host0,self.host1)

        time.sleep(5) # CA-22523

        self.checkMultipath(self.host0,self.MULTIMASTER)

    def checkMultipath(self,host,enabled):

        # Check multipath config on host
        xenrt.TEC().logverbose("Checking multipath config on %s" % 
                               (host.getName()))

        mpdevs = host.getMultipathInfo()
        mpdevs_mpp, mppaths_mpp = host.getMultipathInfoMPP()
        pbd = host.parseListForUUID("pbd-list",
                                    "sr-uuid",
                                    self.sr.uuid,
                                    "host-uuid=%s" % (host.getMyHostUUID()))
        scsiid = host.genParamGet("pbd", pbd, "device-config", "SCSIid")

        if enabled:       
            if not self.MPP_RDAC:
                if len(mpdevs[scsiid]) != self.numpaths:
                    raise xenrt.XRTFailure("Incorrect number of paths found",
                                           "Expected %d got %u (%s)" %
                                           (self.numpaths, len(mpdevs[scsiid]),
                                            string.join(mpdevs[scsiid])))
                for dev in mpdevs[scsiid]:
                    id = host.getSCSIID(dev)
                    if id != scsiid:
                        raise xenrt.XRTFailure("Multipath SCSI ID mismatch",
                                               "Expecting %s but %s was %s" %
                                               (scsiid, dev, id))
                targets = host.execdom0("ls /dev/iscsi/%s" % (self.targetiqn)).split()
                if len(targets) != 2:
                    raise xenrt.XRTFailure("Incorrect number of targets found",
                                           "Expected 2 got %u (%s)" %
                                           (len(targets),
                                            string.join(targets)))
                                 
                for target in targets:
                    dev = host.execdom0("readlink -f /dev/iscsi/%s/%s/LUN%d"
                                        % (self.targetiqn, target, self.lunid)).strip()
                    if not os.path.basename(dev) in mpdevs[scsiid]:
                        raise xenrt.XRTFailure("iSCSI device not found in multipath",
                                               "%s LUN %d is %s, not in %s" %
                                               (target,
                                                self.lunid,
                                                dev,
                                                string.join(mpdevs[scsiid])))
            else:
                if mppaths_mpp[scsiid] != self.numpaths:
                    raise xenrt.XRTFailure("Incorrect number of paths found",
                                           "Expected %d got %u" %
                                           (self.numpaths, mppaths_mpp[scsiid]))
                id = host.getSCSIID(mpdevs_mpp[scsiid])
                if id != scsiid:
                    raise xenrt.XRTFailure("Multipath SCSI ID mismatch",
                                           "Expecting %s but %s was %s" %
                                           (scsiid, mpdevs_mpp[scsiid], id))
        else:
            # Check multipath daemon is turned off
            # Config should be disabled
            try:
                cf = host.execdom0("readlink /etc/multipath.conf")
                if os.path.basename(cf.strip()) != "multipath-disabled.conf":
                    raise xenrt.XRTFailure("Multipath daemon not disabled when "
                                           "multipathing turned off")
            except:
                pass

            # Check that multipath -l gives no output
            if mpdevs.has_key(scsiid):
                raise xenrt.XRTFailure("Multipath information found when "
                                       "multipathing disabled")

            # Check that the 'mpp_mpathutil.py pathinfo' gives no output
            if mpdevs_mpp.has_key(scsiid):
                raise xenrt.XRTFailure("MPP RDAC multipath information found when "
                                       "multipathing disabled")

    def run(self, arglist=None):
        # Join slave to master...
        self.pool.addHost(self.host1)

        # Wait for the host to become enabled
        self.host1.waitForEnabled(300)

        # Check it worked
        self.checkMultipath(self.host0,self.MULTIMASTER)
        self.checkMultipath(self.host1,self.MULTISLAVE)
        self.pool.check()
        self.sr.check()

        # Create a 256M VDI on the SR
        cli = self.pool.getCLIInstance()
        args = []
        args.append("name-label='XenRT Test VDI on %s'" % (self.sr.uuid))
        args.append("sr-uuid=%s" % (self.sr.uuid))
        args.append("virtual-size=268435456") # 256M
        args.append("type=user")
        vdi = cli.execute("vdi-create", string.join(args), strip=True)

        # Attach vdi to dom0 on the master, and create a filesystem
        args = []
        args.append("vm-uuid=%s" % (self.host0.getMyDomain0UUID()))
        args.append("vdi-uuid=%s" % (vdi))
        args.append("device=autodetect")
        vbd = cli.execute("vbd-create", string.join(args), strip=True)
        cli.execute("vbd-plug","uuid=%s" % (vbd))
        time.sleep(5)
        dev = self.host0.genParamGet("vbd", vbd, "device")
        self.host0.execdom0("mkfs.ext3 /dev/%s" % (dev))
        self.host0.execdom0("mkdir -p /tmp/xenrt_multipath")
        self.host0.execdom0("mount /dev/%s /tmp/xenrt_multipath" % (dev))
        self.host0.execdom0("touch /tmp/xenrt_multipath/xenrt_test")
        self.host0.execdom0("umount /tmp/xenrt_multipath")

        # Now unplug and delete the vbd
        cli.execute("vbd-unplug", "uuid=%s" % (vbd))
        cli.execute("vbd-destroy", "uuid=%s" % (vbd))

        # Now create a vbd on the slave, check we can see the file
        args = []
        args.append("vm-uuid=%s" % (self.host1.getMyDomain0UUID()))
        args.append("vdi-uuid=%s" % (vdi))
        args.append("device=autodetect")
        vbd = cli.execute("vbd-create", string.join(args), strip=True)
        cli.execute("vbd-plug","uuid=%s" % (vbd))
        time.sleep(5)
        dev = self.host1.genParamGet("vbd", vbd, "device")
        self.host1.execdom0("mkdir -p /tmp/xenrt_multipath")
        self.host1.execdom0("mount /dev/%s /tmp/xenrt_multipath" % (dev))
        rc = self.host1.execdom0("ls /tmp/xenrt_multipath/xenrt_test")
        self.host1.execdom0("umount /tmp/xenrt_multipath")

        cli.execute("vbd-unplug", "uuid=%s" % (vbd))
        cli.execute("vbd-destroy", "uuid=%s" % (vbd))
        cli.execute("vdi-destroy", "uuid=%s" % (vdi))

    def postRun(self):
        # Forget the SR
        self.host0.forgetSR(self.sr.uuid)
        if self.lun:
            self.lun.release()

class TC10787(TC8031):
    """Join non-multipathed slave to non-multipathed master with an SR on a
       multihomed iSCSI target - MPP"""
    MPP_RDAC = True

class TC8032(TC8031):
    """Join non-multipathed slave to multipathed master with an SR on a
       multihomed iSCSI target """
    MULTIMASTER = True
    MULTISLAVE = False

class TC10788(TC8032):
    """Join non-multipathed slave to multipathed master with an SR on a
       multihomed iSCSI target - MPP"""
    MPP_RDAC = True

class TC8033(TC8031):
    """Join multipathed slave to multipathed master with an SR on a
       multihomed iSCSI target"""
    MULTIMASTER = True
    MULTISLAVE = True

class TC10789(TC8033):
    """Join multipathed slave to multipathed master with an SR on a
       multihomed iSCSI target - MPP"""
    MPP_RDAC = True

class TC8034(TC8031):
    """Join multipathed slave to non-multipathed master with an SR on a
       multihomed iSCSI target"""
    MULTIMASTER = False
    MULTISLAVE = True

class TC10790(TC8034):
    """Join multipathed slave to non-multipathed master with an SR on a
       multihomed iSCSI target - MPP"""
    MPP_RDAC = True

class TC8113(xenrt.TestCase):
    """Verify normal VM lifecycle operations using SR on a multihomed iSCSI
       target"""
    MPP_RDAC = False

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.targethost = None
        self.host0 = None
        self.host1 = None
        self.targetguest = None
        self.guest = None
        self.sr = None
        self.pool = None
        self.iterations = 10
        self.lun = None

    def prepare(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        if not self.MPP_RDAC:
            # Set up iSCSI target with enough space for a debian VM
            self.targethost = self.getHost("RESOURCE_HOST_2")

            nsecaids = self.targethost.listSecondaryNICs("NSEC")
            if len(nsecaids) == 0:
                raise xenrt.XRTError("Could not find a NSEC interface on target"
                                     " host")

            # Prepare a multihomed iSCSI target VM
            self.targetguest = self.targethost.createGenericLinuxGuest()
            bridge1 = self.targethost.getBridgeWithMapping(nsecaids[0])
            self.targetguest.createVIF(eth="eth1", bridge=bridge1, plug=True)
            time.sleep(5)
            self.targetguest.execguest("echo 'auto eth1' >> "
                                       "/etc/network/interfaces")
            self.targetguest.execguest("echo 'iface eth1 inet dhcp' >> "
                                       "/etc/network/interfaces")
            self.targetguest.execguest("echo 'post-up route del -net default "
                                       "dev eth1' >> /etc/network/interfaces")
            self.targetguest.execguest("ifup eth1")
            self.uninstallOnCleanup(self.targetguest)
            self.getLogsFrom(self.targetguest)
            
            # Set up an extra 20G disk
            dev = self.targetguest.createDisk(sizebytes=21474836480, returnDevice=True)
            self.targetguest.execguest("mkfs.ext3 /dev/%s" % dev)
            self.targetguest.execguest("mkdir -p /iscsi")
            self.targetguest.execguest("mount /dev/%s /iscsi" % dev)

            self.initiator = "xenrt-test"
            self.targetiqn = self.targetguest.installLinuxISCSITarget()
            self.targetguest.createISCSITargetLun(0, 16192, dir="/iscsi/")
            self.targetip = self.targetguest.getIP()

        # Prepare the two hosts, enable multipathing, create SR and join
        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host0.resetToFreshInstall()
        self.host1.resetToFreshInstall()

        # Set up NICs on master and slave
        h0nsecaids = self.host0.listSecondaryNICs("NSEC")
        if len(h0nsecaids) == 0:
            raise xenrt.XRTError("Could not find a NSEC interface on host %s" %
                                 (self.host0.getName()))
        self.host0.setIPAddressOnSecondaryInterface(h0nsecaids[0])
        h1nsecaids = self.host1.listSecondaryNICs("NSEC")
        if len(h1nsecaids) == 0:
            raise xenrt.XRTError("Could not find a NSEC interface on host %s" %
                                 (self.host1.getName()))
        self.host1.setIPAddressOnSecondaryInterface(h1nsecaids[0])

        # Enable multipathing
        self.host0.enableMultipathing(mpp_rdac=self.MPP_RDAC)
        self.host1.enableMultipathing(mpp_rdac=self.MPP_RDAC)

        # Create the pool object
        self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)

        # Setup iSCSI SR on master
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host0,
                                                             "TC8113", thinprov)

        if not self.MPP_RDAC:
            self.lun = xenrt.ISCSILunSpecified("%s/%s/%s" %
                                          (self.initiator,
                                           self.targetiqn,
                                           self.targetip))
        else:
            self.lun = xenrt.ISCSILun(minsize=50,mpprdac=True)
            self.initiator = self.lun.getInitiatorName()
            self.targetiqn = self.lun.getTargetName()
            self.targetip = self.lun.getServer()
            self.lunid = self.lun.getID()

        self.sr.create(self.lun, subtype="lvm", findSCSIID=(not self.MPP_RDAC), mpp_rdac=self.MPP_RDAC)
        self.sr.prepareSlave(self.host0,self.host1)

        # Join hosts into a pool
        self.pool.addHost(self.host1)

    def run(self, arglist=None):
        # Install a Debian VM, and perform a quick set of operations
        # as subcases
        operations = ["installVM", "stopStart", "reboot", "suspendResume",
                      "migrate", "liveMigrate"]
        for op in operations:
            rc = self.runSubcase(op, (), op, op)
            if rc == xenrt.RESULT_FAIL:
                raise xenrt.XRTFailure("%s failed" % (op))
            elif rc == xenrt.RESULT_ERROR:
                raise xenrt.XRTError("%s errored" % (op))

    def installVM(self):
        self.guest = self.pool.master.createGenericLinuxGuest(sr=self.sr.uuid)

    def stopStart(self):
        for i in range(self.iterations):
            self.guest.shutdown()
            self.guest.start()
            self.guest.check()

    def reboot(self):
        for i in range(self.iterations):
            self.guest.reboot()
            self.guest.check()

    def suspendResume(self):
        for i in range(self.iterations):
            self.guest.suspend()
            self.guest.resume()
            self.guest.check()

    def migrate(self):
        for i in range(self.iterations):
            if self.guest.host == self.host0:
                dest = self.host1
            else:
                dest = self.host0
            self.guest.migrateVM(dest)
            self.guest.check()

    def liveMigrate(self):
        for i in range(self.iterations):
            if self.guest.host == self.host0:
                dest = self.host1
            else:
                dest = self.host0
            self.guest.migrateVM(dest,live="true")
            self.guest.check()

    def postRun(self):
        if self.lun:
            self.lun.release()

class TC10791(TC8113):
    """Verify normal VM lifecycle operations using SR on a multihomed iSCSI
       target - MPP"""
    MPP_RDAC = True
       
# Failure/Recovery TCs (TC-8136)

class _TC8133(xenrt.TestCase):
    """Base class for TC-8133 style TCs"""
    USEVLANS = False    # Whether to use VLANs or not
    FAIL = "PRIMARY"    # Whether to fail a primary or a secondary path
    MPP_RDAC = False    # Do we enable MPP-RDAC

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.target = None
        self.scsiID = None
        self.failIF = None
        self.host = None
        self.pbd = None
        self.lun = None

    def prepare(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        # Get 2 hosts
        self.host = self.getHost("RESOURCE_HOST_0")
        if not self.MPP_RDAC:
            self.targetHost = self.getHost("RESOURCE_HOST_1")

        # Reset the hosts to fresh installs
        self.host.resetToFreshInstall()
        if not self.MPP_RDAC:
            self.targetHost.resetToFreshInstall()

        # Configure the host networking
        if self.USEVLANS:
            netconfig = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>   
    <VLAN network="VR01"> 
      <STORAGE/>
    </VLAN>
    <MANAGEMENT/>
  </PHYSICAL>    
  <PHYSICAL network="NSEC">
    <NIC/>
    <VLAN network="VR02">
      <STORAGE/>
    </VLAN>
    <STORAGE/>
  </PHYSICAL>
</NETWORK>"""
            self.paths = 4
        else:
            netconfig = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>   
    <MANAGEMENT/>
  </PHYSICAL>    
  <PHYSICAL network="NSEC">
    <NIC/>
    <STORAGE/>
  </PHYSICAL>
</NETWORK>"""
            self.paths = 2

        self.host.createNetworkTopology(netconfig)
        
        if not self.MPP_RDAC:
            self.targetHost.createNetworkTopology(netconfig)
            self.target = self.targetHost.createGenericLinuxGuest()
            secnetworks = self.targetHost.minimalList("network-list")
            eIndex = 1
            for n in secnetworks:
                bridge = self.targetHost.genParamGet("network", n, "bridge")
                try:
                    if bridge == self.targetHost.getPrimaryBridge() or \
                       self.targetHost.genParamGet("network", n, "other-config",
                                           "is_guest_installer_network") == "true":
                        continue
                except:
                    # We get an exception if the is_guest_installer_network key
                    # doesn't exist...
                    pass
                # See if the PIF associated with this network has an IP on
                pif = self.targetHost.minimalList("pif-list", args="network-uuid=%s" % (n))[0]
                if self.targetHost.genParamGet("pif", pif, "IP-configuration-mode") == "None":
                    continue
                self.target.createVIF(eth="eth%u" % (eIndex), bridge=bridge, 
                                      plug=True)
                time.sleep(5)
                self.target.execguest("echo 'auto eth%u' >> "
                                      "/etc/network/interfaces" % (eIndex))
                self.target.execguest("echo 'iface eth%u inet dhcp' >> "
                                      "/etc/network/interfaces" % (eIndex))
                self.target.execguest("echo 'post-up route del -net default dev "
                                      "eth%u' >> /etc/network/interfaces" % (eIndex))
                self.target.execguest("ifup eth%u" % (eIndex))
                eIndex += 1

            self.uninstallOnCleanup(self.target)
            self.getLogsFrom(self.target)

            # Configure large iSCSI target on second host
            dev = self.target.createDisk(sizebytes=10737418240, returnDevice=True)
            time.sleep(5)
            self.target.execguest("mkfs.ext3 /dev/%s" % dev)
            self.target.execguest("mkdir -p /iscsi")
            self.target.execguest("mount /dev/%s /iscsi" % dev)
            self.initiator = "xenrt-test"
            self.targetiqn = self.target.installLinuxISCSITarget()
            self.target.createISCSITargetLun(0, 8096, dir="/iscsi/")
            self.targetip = self.target.getIP()
            self.lunid = 0
        else:
            self.paths = 4

        # Set up the SR on the host
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,
                                                             "_TC8133", thinprov)
        
        if not self.MPP_RDAC:
            self.lun = xenrt.ISCSILunSpecified("%s/%s/%s" %
                                          (self.initiator,
                                           self.targetiqn,
                                           self.targetip))
        else:
            self.lun = xenrt.ISCSILun(minsize=50,mpprdac=True)
            self.initiator = self.lun.getInitiatorName()
            self.targetiqn = self.lun.getTargetName()
            self.targetip = self.lun.getServer()
            self.lunid = self.lun.getID()

        sr.create(self.lun, subtype="lvm", findSCSIID=(not self.MPP_RDAC),
            multipathing=True, mpp_rdac=self.MPP_RDAC)
        
        pbd = self.host.parseListForUUID("pbd-list",
                                    "sr-uuid",
                                    sr.uuid,
                                    "host-uuid=%s" % (self.host.getMyHostUUID()))
        self.pbd = pbd
        self.scsiID = self.host.genParamGet("pbd", pbd, "device-config", "SCSIid")
        data = self.host.genParamGet("pbd", pbd, "device-config", "multihomelist")
        self.multihomelist = data.split(',')

        time.sleep(30)

        # Check we see the requisite number of paths
        if not self.MPP_RDAC:
            mp = self.host.getMultipathInfo()
            if len(mp[self.scsiID]) != self.paths:
                raise xenrt.XRTError("Only found %u/%u paths in multipath output" % 
                                     (len(mp[self.scsiID]),self.paths))
            mp = self.host.getMultipathInfo(onlyActive=True)
            if len(mp[self.scsiID]) != self.paths:
                raise xenrt.XRTError("Only %u/%u paths active before test started" %
                                     (len(mp[self.scsiID]),self.paths))
        else:
            mpdev, mppaths = self.host.getMultipathInfoMPP()
            if not mpdev.has_key(self.scsiID):
                raise xenrt.XRTError("SCSIID %s not found in MPP RDAC status info" % self.scsiID)
            if mppaths[self.scsiID] != self.paths:
                raise xenrt.XRTError("Only found %u/%u paths in multipath output" % 
                                     (mppaths[self.scsiID],self.paths))
            mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
            if mppaths[self.scsiID] != self.paths:
                raise xenrt.XRTError("Only %u/%u paths active before test started" %
                                     (mppaths[self.scsiID],self.paths))

        counts = self.host.getMultipathCounts(self.pbd, self.scsiID)
        if counts[0] != self.paths or \
           counts[1] != self.paths:
            if xenrt.TEC().lookup("WARN_ONLY_CA22607", False, boolean=True):
                xenrt.TEC().warning("Multipath counts on PBD wrong before test "
                                    "started - expecting all %u active, found "
                                    "%u/%u" % (self.paths,counts[0],counts[1]))
            else:
                raise xenrt.XRTError("Multipath counts on PBD wrong before test "
                                     "started - expecting all %u active, found "
                                     "%u/%u" % (self.paths,counts[0],counts[1]))

        if self.FAIL == "PRIMARY":
            self.failIF = "eth0"
            self.failIP = self.targetip
        else:
            self.failIF = "eth1"
            self.failIP = self.multihomelist[1].split(':')[0]

        # Set up VM with VDI on SR, periodically reading/writing
        self.guest = self.host.createGenericLinuxGuest()
        self.dev = self.guest.createDisk(sizebytes=5368709120, sruuid=sr.uuid, returnDevice=True) # 5GB
        time.sleep(5)
        # Launch a periodic read/write script using the new disk
        self.guest.execguest("%s/remote/readwrite.py /dev/%s > /tmp/rw.log "
                             "2>&1 < /dev/null &" %
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.dev))


    def check(self):
        # Check the periodic read/write script is still running on the VM
        rc = self.guest.execguest("pidof python",retval="code")
        if rc > 0:
            # Get the log
            self.guest.execguest("cat /tmp/rw.log || true")
            raise xenrt.XRTFailure("Periodic read/write script failed")

        try:
            line = ''
            line = self.guest.execguest("tail -n 1 /tmp/rw.log").strip()
            if(len(line) == 0):
                raise xenrt.XRTError("/tmp/rw.log file is empty ")
            first = int(float(line))
            time.sleep(30)
            line = ''
            line = self.guest.execguest("tail -n 1 /tmp/rw.log").strip()
            if(len(line) == 0):
                raise xenrt.XRTError("/tmp/rw.log file is empty")
            next = int(float(line))
            if next == first:
                raise xenrt.XRTFailure("Periodic read/write script has not "
                                       "completed a loop in 30 seconds")

        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTError("Exception checking read/write script progress",
                                 data=str(e))

    def run(self, arglist=None):
        # Interrupt the relevant path
        if not self.MPP_RDAC:
            self.target.execguest("iptables -I INPUT -i %s -p tcp -m tcp "
                                  "--dport 3260 -j DROP" % (self.failIF))
            self.target.execguest("iptables -I OUTPUT -o %s -p tcp -m tcp "
                                  "--sport 3260 -j DROP" % (self.failIF))
        else:
            self.host.execdom0("iptables -I OUTPUT -d %s -j DROP" % (self.failIP))
                                  
        # Wait 50 seconds (as defined in the requirements)
        time.sleep(50)

        # Verify that the path is detected as failed
        if not self.MPP_RDAC:
            mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
            if len(mp[self.scsiID]) != (self.paths - 1):
                raise xenrt.XRTFailure("Expecting %u/%u paths active, found %u" %
                                       ((self.paths - 1),self.paths,
                                        len(mp[self.scsiID])))
        else:
            mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
            if mppaths[self.scsiID] != (self.paths - 1):
                raise xenrt.XRTFailure("Expecting %u/%u paths active, found %u" %
                                       ((self.paths - 1),self.paths,
                                        mppaths[self.scsiID]))

        # Wait a further 10 seconds to allow mpathcount etc to run
        time.sleep(10)

        # Check the count matches what we expect
        counts = self.host.getMultipathCounts(self.pbd, self.scsiID)
        if counts[0] != (self.paths - 1) or \
           counts[1] != self.paths:
            raise xenrt.XRTFailure("Multipath counts on PBD wrong - expecting "
                                   "%u/%u, found %u/%u" % 
                                   ((self.paths - 1), self.paths, counts[0],
                                    counts[1]))
        
        # Check the SR is still functional
        self.check()

        # Restore the path
        if not self.MPP_RDAC:
            self.target.execguest("iptables -D INPUT -i %s -p tcp -m tcp "
                                  "--dport 3260 -j DROP" % (self.failIF))
            self.target.execguest("iptables -D OUTPUT -o %s -p tcp -m tcp "
                                  "--sport 3260 -j DROP" % (self.failIF))
        else:
            self.host.execdom0("iptables -D OUTPUT -d %s -j DROP" % (self.failIP))
            
        # Wait 2 minutes (CA-72427)
        time.sleep(120)

        # Verify that the path is detected as active
        if not self.MPP_RDAC:
            mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
            if len(mp[self.scsiID]) != self.paths:
                raise xenrt.XRTFailure("Expecting all %u paths active, found %u" %
                                       (self.paths,len(mp[self.scsiID])))
        else:
            mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
            if mppaths[self.scsiID] != self.paths:
                raise xenrt.XRTFailure("Expecting all %u paths active, found %u" %
                                       (self.paths,mppaths[self.scsiID]))

        # Check the count matches what we expect
        counts = self.host.getMultipathCounts(self.pbd, self.scsiID)
        if counts[0] != self.paths or \
           counts[1] != self.paths:
            raise xenrt.XRTFailure("Multipath counts on PBD wrong - expecting "
                                   "all %u paths active, found %u/%u" %
                                   (self.paths, counts[0], counts[1]))

        # Check the SR is still functional
        self.check()

    def postRun(self):
        if self.lun:
            self.lun.release()

class TC8133(_TC8133):
    """Primary path failure/recovery handling (2 paths total)"""
    pass
    
class TC8134(_TC8133):
    """Secondary path failure/recovery handling (2 paths total)"""
    FAIL = "SECONDARY"

class TC8135(_TC8133):
    """Secondary path failure/recovery handling (4 paths total)"""
    USEVLANS = True
    FAIL = "SECONDARY"
    
class TC10769(_TC8133):
    """Primary path failure/recovery handling (4 paths total) - MPP"""
    MPP_RDAC = True

class TC10771(_TC8133):
    """Secondary path failure/recovery handling (4 paths total) - MPP"""
    FAIL = "SECONDARY"
    MPP_RDAC = True

class _TC8137(_TC8133):
    """Base class for TC-8137 style TCs"""
    USEVLANS = False
    RECOVER = "PRIMARY"     # Which path to recover
    MPP_RDAC = False

    def blockPath(self, path, block=True):
        if path == "PRIMARY":
            intf = "eth0"
            ip = self.targetip
        elif path == "SECONDARY":
            intf = "eth1"
            ip = self.multihomelist[1].split(':')[0]
        elif path == "TERTIARY":
            intf = "eth2"
            ip = self.multihomelist[2].split(':')[0]
        elif path == "QUATERNARY":
            intf = "eth3"
            ip = self.multihomelist[3].split(':')[0]
        if block:
            opt = "I"
        else:
            opt = "D"
        if not self.MPP_RDAC:
            self.target.execguest("iptables -%s INPUT -i %s -p tcp -m tcp "
                                  "--dport 3260 -j DROP" % (opt, intf))
            self.target.execguest("iptables -%s OUTPUT -o %s -p tcp -m tcp "
                                  "--sport 3260 -j DROP" % (opt, intf))
        else:
            self.host.execdom0("iptables -%s OUTPUT -d %s -j DROP" % (opt, ip))

    def run(self, arglist=None):
        # Interrupt both paths
        self.blockPath("PRIMARY")
        self.blockPath("SECONDARY")
        if self.paths > 2:
            self.blockPath("TERTIARY")
        if self.paths > 3:
            self.blockPath("QUATERNARY")

        # Wait 50 seconds
        time.sleep(50)

        # Verify that both paths are detected as failed
        if not self.MPP_RDAC:
            mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
            if not mp.has_key(self.scsiID):
                self.pause("CA-25156 Repro Detected")
            if len(mp[self.scsiID]) != 0:
                raise xenrt.XRTFailure("Expecting 0 paths active, found %u" %
                                       (len(mp[self.scsiID])))
        else:
            mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
            if not mpdev.has_key(self.scsiID):
                self.pause("CA-25156 Repro Detected")
            if mppaths[self.scsiID] != 0:
                raise xenrt.XRTFailure("Expecting 0 paths active, found %u" %
                                       (mppaths[self.scsiID]))
        
        time.sleep(10)
        # Check the multipath counts
        counts = self.host.getMultipathCounts(self.pbd, self.scsiID)
        if counts[0] != 0 or counts[1] != self.paths:
            raise xenrt.XRTFailure("Multipath counts on PBD wrong - expecting "
                                   "0/%u, found %u/%u" %
                                   (self.paths, counts[0], counts[1]))
       
        expectedPaths = 1
        if self.RECOVER == "BOTH":
            self.blockPath("PRIMARY", block=False)
            self.blockPath("SECONDARY", block=False)
            expectedPaths = 2
        else:
            self.blockPath(self.RECOVER, block=False)

        # Wait 60 seconds
        time.sleep(60)        

        
        # Verify that we have expectedPaths active
        if not self.MPP_RDAC:
            mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
            if len(mp[self.scsiID]) != expectedPaths:
                raise xenrt.XRTFailure("Expecting %u/2 paths active, found %u" %
                                       (expectedPaths,len(mp[self.scsiID])))
        else:
            mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
            if mppaths[self.scsiID] != expectedPaths:
                raise xenrt.XRTFailure("Expecting %u/2 paths active, found %u" %
                                       (expectedPaths,mppaths[self.scsiID]))

        # Check the multipath counts
        counts = self.host.getMultipathCounts(self.pbd, self.scsiID)
        if counts[0] != expectedPaths or counts[1] != self.paths:
            raise xenrt.XRTFailure("Multipath counts on PBD wrong - expecting "
                                   "%u/%u, found %u/%u" %
                                   (expectedPaths, self.paths, counts[0], counts[1]))

        # Check the SR is still functional
        self.check()

        # Restart the read/write script and check it works
        self.guest.execguest("killall -9 python || true")
        self.guest.execguest("%s/remote/readwrite.py /dev/%s > /tmp/rw.log "
                             "2>&1 < /dev/null &" %
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.dev))
        time.sleep(5)

class TC8137(_TC8137):
    """Recovery of only primary path after both path failure"""
    pass

class TC8138(_TC8137):
    """Recovery of only secondary path after both path failure"""
    RECOVER = "SECONDARY"

class TC8139(_TC8137):
    """Recovery of both paths after both path failure"""
    RECOVER = "BOTH"

class TC10772(TC8137):
    """Recovery of only primary path after two path failure - MPP"""
    MPP_RDAC = True

class TC10773(TC8138):
    """Recovery of only secondary path after two path failure - MPP"""
    MPP_RDAC = True

class TC10774(TC8139):
    """Recovery of both paths after two path failure - MPP"""
    MPP_RDAC = True

class TC8140(_TC8137):
    """Swap failed paths"""
    USEVLANS = False
    MPP_RDAC = False

    def run(self, arglist=None):
        # Interrupt the primary path (and any other, leaving only the secondary path)
        self.blockPath("PRIMARY")
        if self.paths > 2:
            self.blockPath("TERTIARY")
        if self.paths > 3:
            self.blockPath("QUATERNARY")
            
        # Wait 50 seconds
        time.sleep(50)

        # Verify the path is detected as failed
        if not self.MPP_RDAC:
            mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
            if len(mp[self.scsiID]) != 1:
                raise xenrt.XRTFailure("Expecting 1/%u paths active, found %u" %
                                       (self.paths, len(mp[self.scsiID])))
        else:
            mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
            if mppaths[self.scsiID] != 1:
                raise xenrt.XRTFailure("Expecting 1/%u paths active, found %u" %
                                       (self.paths, mppaths[self.scsiID]))

        self.check()
        time.sleep(60)

        # Interrupt the secondary path and recover the primary path
        self.blockPath("SECONDARY")
        self.blockPath("PRIMARY", False)

        # Wait 50 seconds
        time.sleep(50)

        # Verify we still see one path XXX This should probably check it's the
        # expected path!
        if not self.MPP_RDAC:
            mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
            if len(mp[self.scsiID]) != 1:
                raise xenrt.XRTFailure("Expecting 1/%u paths active, found %u" %
                                       (self.paths, len(mp[self.scsiID])))
        else:
            mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
            if mppaths[self.scsiID] != 1:
                raise xenrt.XRTFailure("Expecting 1/%u paths active, found %u" %
                                       (self.paths, mppaths[self.scsiID]))

        self.check()

class TC10775(TC8140):
    """Swap failed paths - MPP"""
    MPP_RDAC = True
    
class TC8141(_TC8137):
    """Loop of fail-recover on alternate paths"""
    USEVLANS = False
    DEFAULT_LOOPS = 100
    MPP_RDAC = False

    def run(self, arglist=None):
        if arglist and len(arglist) > 0:
            loops = int(arglist[0])
        else:
            loops = self.DEFAULT_LOOPS

        # Interrupt any paths beyond the secondary path
        if self.paths > 2:
            self.blockPath("TERTIARY")
        if self.paths > 3:
            self.blockPath("QUATERNARY")
            
        failPrimary = True
        fail = "PRIMARY"
        for i in range(loops):
            xenrt.TEC().logverbose("Starting loop iteration %u/%u" % 
                                   (i+1,loops))

            self.blockPath(fail)

            # Wait 50 seconds
            time.sleep(50) 

            # Verify path is detected as 
            if not self.MPP_RDAC:
                mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
                if len(mp[self.scsiID]) != 1:
                    raise xenrt.XRTFailure("Expecting 1/%u paths active, found %u" %
                                           (self.paths, len(mp[self.scsiID])))
            else:
                mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
                if mppaths[self.scsiID] != 1:
                    raise xenrt.XRTFailure("Expecting 1/%u paths active, found %u" %
                                           (self.paths, mppaths[self.scsiID]))

            self.check()

            # Recover the path
            self.blockPath(fail, False)
            
            # Wait 60 seconds
            time.sleep(60)

            # Verify path is detected as active
            if not self.MPP_RDAC:
                mp = self.host.getMultipathInfo(onlyActive=True, useLL=True)
                if len(mp[self.scsiID]) != 2:
                    raise xenrt.XRTFailure("Expecting 2/%u paths active, found %u" %
                                           (self.paths, len(mp[self.scsiID])))
            else:
                mpdev, mppaths = self.host.getMultipathInfoMPP(onlyActive=True)
                if mppaths[self.scsiID] != 2:
                    raise xenrt.XRTFailure("Expecting 2/%u paths active, found %u" %
                                           (self.paths, mppaths[self.scsiID]))

            self.check()

            if fail == "PRIMARY":
                fail = "SECONDARY"
            else:
                fail = "PRIMARY"
 
class TC10776(TC8141):
    """Loop of fail-recover on alternate paths - MPP"""
    MPP_RDAC = True
    DEFAULT_LOOPS = 50
    
class _TC8159(xenrt.TestCase):
    """Base class for TC-8159 and TC-8160"""
    PATHS = 1 # Expect 1 path
    NOT_MULTIPATHED = False
    MORE_PATHS_OK = False # Set to true for e.g. FC tests where our hardware
                          # might have more paths than we really need

    def __init__(self, tcid=None):
        self.guest = None
        self.sr = None
        self.scsiid = None
        self.napp = None
        self.lun = None
        xenrt.TestCase.__init__(self, tcid=tcid)

    def run(self, arglist=None):
        # This test assumes that the host networking has already been set up etc
        host = self.getDefaultHost()

        # Create a multipathed SR
        sr = self.createSR(host)
        self.sr = sr

        # Get the contents of /dev/disk/by-id
        ids = host.execdom0("ls /dev/disk/by-id").strip().split("\n")

        # Create a VM on the SR
        g = host.createBasicGuest(distro='rhel5x',sr=sr.uuid)
        self.guest = g
        expectedDiskCount = len(self.guest.listVBDUUIDs("Disk"))

        # Verify the lun(s) for the VM are using multipathing and that all
        # paths are available

        if self.scsiid:
            scsiids = [self.scsiid]
        else:
            # Find the SCSIIDs by diffing /dev/disk/by-id
            newids = host.execdom0("ls /dev/disk/by-id").strip().split("\n")
            scsiids = []
            for ni in newids:
                if re.match("\S+-part\d", ni):
                    # -part# - ignore it...
                    continue
                if ni in ids:
                    # Existing thing, probably a local disk
                    continue
                # XRT-3822 Remove scsi-
                m = re.match("scsi-(\S+)", ni)
                if m:
                    ni = m.group(1)

                scsiids.append(ni)

            if len(scsiids) != expectedDiskCount:
                raise xenrt.XRTError("Found %u new IDs - expecting %u" % 
                                     (len(scsiids), expectedDiskCount))

        mp = host.getMultipathInfo()
        amp = host.getMultipathInfo(onlyActive=True)
        if self.NOT_MULTIPATHED:
            for scsiid in scsiids:
                if scsiid in mp:
                    raise xenrt.XRTFailure("Multipathed device found when not "
                                           "expected", data=scsiid)
        else:
            for scsiid in scsiids:
                if not scsiid in mp:
                    raise xenrt.XRTFailure("Device not found in multipath "
                                           "output", data=scsiid)
                if self.MORE_PATHS_OK:
                    if len(mp[scsiid]) < self.PATHS:
                        raise xenrt.XRTFailure("Only found %u/%u paths" % 
                                               (len(mp[scsiid]), self.PATHS),
                                               data=scsiid)
                else:
                    if len(mp[scsiid]) != self.PATHS:
                        raise xenrt.XRTFailure("Only found %u/%u paths" % 
                                               (len(mp[scsiid]), self.PATHS),
                                               data=scsiid)
                if not scsiid in amp:
                    raise xenrt.XRTFailure("Device found with no active paths",
                                           data=scsiid)
                if self.MORE_PATHS_OK:
                    if len(amp[scsiid]) < self.PATHS:
                        raise xenrt.XRTFailure("Only %u/%u paths active" %
                                               (len(amp[scsiid]), self.PATHS),
                                               data=scsiid)
                else:
                    if len(amp[scsiid]) != self.PATHS:
                        raise xenrt.XRTFailure("Only %u/%u paths active" %
                                               (len(amp[scsiid]), self.PATHS),
                                               data=scsiid)

        # Verify the guest is running correctly
        self.guest.check()

    def postRun(self):
        if self.guest:
            try:
                self.guest.shutdown()
                self.guest.uninstall()
            except:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception removing guest")
        if self.sr:
            try:
                self.sr.remove()
            except:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception removing SR")
        if self.napp:
            self.napp.release()
        if self.lun:
            self.lun.release()

    def createSR(self, host):
        raise xenrt.XRTError("Unimplemented")

class TC8159(_TC8159):
    """Multipathing setup and SR creation using NetApp SR (4 paths)"""
    PATHS = 4 # 4 Paths

    def createSR(self, host):
        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.napp = napp
        sr = xenrt.lib.xenserver.NetAppStorageRepository(host, "xenrtnetapp")
        sr.create(napp,multipathing=True)
        return sr

class TC8620(TC8159):
    """Multipathing setup and SR creation using NetApp SR (2 paths)"""
    PATHS = 2 # 2 Paths
class TC9765(_TC8159):
    """Multipathing setup and SR creation using CVSM SR (4 paths)"""
    PATHS = 4 # 4 Paths

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.cvsmserver = xenrt.CVSMServer(xenrt.TEC().registry.guestGet("CVSMSERVER"))
        self.sr = xenrt.lib.xenserver.CVSMStorageRepository(self.host,
                                                                 "cslgsr")
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        self.napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.cvsmserver.addStorageSystem(self.napp)
        self.sr.create(self.cvsmserver,
                       self.napp,
                       protocol="iscsi",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC9766(TC9765):
    """Multipathing setup and SR creation using CVSM SR (2 paths)"""
    PATHS = 2 # 2 Paths

class TC12900(TC9765):
    """Multipathing setup and SR creation using integrated CVSM SR (4 paths)"""
    PATHS = 4 # 4 Paths

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        self.napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.sr.create(self.napp,
                       protocol="iscsi",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC13991(TC12900):
    """Multipathing setup and SR creation using integrated CVSM SR (4 paths)"""
    PATHS = 4 # 4 Paths

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_EQL_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_EQL_MAXSIZE", 1000000))
        eqlt = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
        self.napp = eqlt # This also has a release method
        self.sr.create(self.napp,
                       protocol="iscsi",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC8160(_TC8159):
    """Multipathing setup and SR creation using Equallogic SR"""
    PATHS = 1 # 1 Path
    NOT_MULTIPATHED = True # We expect it not to show up in multipath output

    def createSR(self, host):
        minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
        maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
        eqlt = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
        self.napp = eqlt # This also has a release method
        sr = xenrt.lib.xenserver.EQLStorageRepository(host, "xenrteql")
        sr.create(eqlt,multipathing=True)
        return sr

class TC9075(_TC8159):
    """Multipathing setup and SR creation using FC (lvmohba) SR"""
    PATHS = 2 # 2 paths
    MORE_PATHS_OK = True
    
    def createSR(self, host):
        lun = xenrt.HBALun(self.getAllHosts())
        self.scsiid = lun.getID()
        sr = xenrt.lib.xenserver.FCStorageRepository(host, "fc")
        sr.create(lun,multipathing=True)
        return sr

class TC9771(_TC8159):
    """Multipathing setup and CVSM-SR creation using FC"""
    PATHS = 2 # 2 paths
    MORE_PATHS_OK = True

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.cvsmserver = xenrt.CVSMServer(xenrt.TEC().registry.guestGet("CVSMSERVER"))
        self.sr = xenrt.lib.xenserver.CVSMStorageRepository(self.host,
                                                                 "cslgsr")
        self.fcarray = xenrt.FCHBATarget()
        self.cvsmserver.addStorageSystem(self.fcarray)
        self.sr.create(self.cvsmserver,
                       self.fcarray,
                       protocol="fc",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC12735(TC9771):
    """Multipathing setup and integrated CVSM-SR creation using FC"""
    PATHS = 2 # 2 paths
    MORE_PATHS_OK = True

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        self.fcarray = xenrt.FCHBATarget()
        self.sr.create(self.fcarray,
                       protocol="fc",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC13986(TC12735):
    """Multipathing setup and integrated CVSM-SR creation using FC"""
    PATHS = 2 # 2 paths
    MORE_PATHS_OK = True

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        self.fcarray = xenrt.FCHBATarget()
        self.sr.create(self.fcarray,
                       protocol="fc",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class _MultipathFailureSmoketest(_TC8159):
    """Base class for multipath failure smoketests"""
    PATHS = 1

    def __init__(self, tcid=None):
        _TC8159.__init__(self, tcid=tcid)
        self.blockips = []

    def run(self, arglist=None):
        # This test assumes that the host networking has already been set up etc
        host = self.getDefaultHost()
        self.host = host

        # Create a multipathed SR
        sr = self.createSR(host)
        self.sr = sr

        # Get the contents of /dev/disk/by-id
        ids = host.execdom0("ls /dev/disk/by-id").strip().split("\n")

        # Create a VM on the SR
        g = host.createGenericLinuxGuest(sr=sr.uuid)
        self.guest = g
        self.uninstallOnCleanup(g)
        expectedDiskCount = len(self.guest.listVBDUUIDs("Disk"))

        # Verify the lun(s) for the VM are using multipathing and that all
        # paths are available

        # Find the SCSIIDs by diffing /dev/disk/by-id
        newids = host.execdom0("ls /dev/disk/by-id").strip().split("\n")
        scsiids = []
        for ni in newids:
            if re.match("\S+-part\d", ni):
                # -part# - ignore it...
                continue
            if ni in ids:
                # Existing thing, probably a local disk
                continue
            # XRT-3822 Remove scsi-
            m = re.match("scsi-(\S+)", ni)
            if m:
                ni = m.group(1)

            scsiids.append(ni)

        if len(scsiids) != expectedDiskCount:
            raise xenrt.XRTError("Found %u new IDs - expecting %u" %
                                 (len(scsiids), expectedDiskCount))
        self.scsiids = scsiids

        self.pathCheck()

        # Get the path info
        pbd = host.minimalList("pbd-list", args="sr-uuid=%s" % (sr.uuid))[0]
        pinfo = host.genParamGet("pbd", pbd, "device-config", "multihomelist").strip()

        if (xenrt.TEC().lookup("WORKAROUND_CA60192", False, boolean=True)):
            # do not ever block the control path to the filer until iCSLG has redundant control path
            controlpath_ip = self.napp.getTarget() 
            xenrt.TEC().logverbose("WORKAROUND_CA60192: not blocking control path to IP %s" % controlpath_ip)
            # remove the control path ip from the multihome list
            pinfo = ",".join(filter(lambda p: ((p.split(":")[0]) != controlpath_ip), pinfo.split(",")))

        # Interrupt each path in turn, and ensure everything keeps working
        for p in pinfo.split(","):
            ip = p.split(":")[0]
            self.blockips.append(ip)
            xenrt.TEC().logverbose("Blocking path to IP %s" % (ip))
            inOrOut = random.choice(["INPUT","OUTPUT"])
            sourceOrDest = (inOrOut == "INPUT") and "s" or "d"
            host.execdom0("iptables -I %s -%s %s -j DROP" % (inOrOut,sourceOrDest,ip))
            time.sleep(50)
            xenrt.TEC().logverbose("Checking path count is as expected")
            self.pathCheck(1)
            xenrt.TEC().logverbose("Verifying guest functionality")
            self.guest.check()
            # Check we can cleanly shut down and start up the guest
            self.guest.shutdown()
            self.guest.start()
            # Check we can create VDIs
            ud = self.guest.createDisk(sizebytes=10485760, sruuid=sr.uuid)
            time.sleep(10)
            self.guest.unplugDisk(ud)
            self.guest.removeDisk(ud)
            # Remove the block
            xenrt.TEC().logverbose("Restoring path to IP %s" % (ip))
            host.execdom0("iptables -D %s -%s %s -j DROP" % (inOrOut,sourceOrDest,ip))
            self.blockips.remove(ip)
            time.sleep(60)
            # CA-28160 do a suspend/resume to get both paths used
            self.guest.suspend()
            self.guest.resume()
            xenrt.TEC().logverbose("Checking path count and guest are as expected")
            self.pathCheck()
            self.guest.check()

        # If theres more than 2 paths, interrupt all but one path
        if len(pinfo.split(",")) > 2:
            xenrt.TEC().logverbose("Blocking all but one path")
            blocked = 0
            inOrOut = random.choice(["INPUT","OUTPUT"])
            sourceOrDest = (inOrOut == "INPUT") and "s" or "d"
            for p in pinfo.split(",")[1:]:
                ip = p.split(":")[0]
                self.blockips.append(ip)
                xenrt.TEC().logverbose("Blocking path to IP %s" % (ip))
                host.execdom0("iptables -I %s -%s %s -j DROP" % (inOrOut,sourceOrDest,ip))
                blocked += 1
            time.sleep(50)
            xenrt.TEC().logverbose("Checking path count is as expected")
            self.pathCheck(blocked)
            xenrt.TEC().logverbose("Verifying guest functionality")
            self.guest.check()
            # Check we can cleanly shut down and start up the guest
            self.guest.shutdown()
            self.guest.start()
            # Check we can create VDIs
            ud = self.guest.createDisk(sizebytes=10485760, sruuid=sr.uuid)
            time.sleep(10)
            self.guest.unplugDisk(ud)
            self.guest.removeDisk(ud)
            # Remove the blocks
            for p in pinfo.split(",")[1:]:
                ip = p.split(":")[0]
                xenrt.TEC().logverbose("Restoring path to IP %s" % (ip))
                host.execdom0("iptables -D %s -%s %s -j DROP" % (inOrOut,sourceOrDest,ip))
                self.blockips.remove(ip)
            time.sleep(60)
            # CA-28160 do a suspend/resume to get both paths used
            self.guest.suspend()
            self.guest.resume()
            xenrt.TEC().logverbose("Checking path count and guest are as expected")
            self.pathCheck()
            self.guest.check()

    def pathCheck(self, expectedDown=0):
        mp = self.host.getMultipathInfo()
        amp = self.host.getMultipathInfo(onlyActive=True)
        for scsiid in self.scsiids:
            if not mp.has_key(scsiid) and self.PATHS > 1:
                raise xenrt.XRTFailure("Only found 1/%u paths" % self.PATHS, data=scsiid)
            if len(mp[scsiid]) != self.PATHS:
                raise xenrt.XRTFailure("Only found %u/%u paths" %
                                       (len(mp[scsiid]), self.PATHS),
                                       data=scsiid)
            if len(amp[scsiid]) != (self.PATHS - expectedDown):
                raise xenrt.XRTFailure("%u/%u paths active, expecting %u" %
                                       (len(amp[scsiid]), self.PATHS,
                                        (self.PATHS - expectedDown)),
                                       data=scsiid)

    def postRun(self):
        for ip in self.blockips:
            try:
                self.host.execdom0("iptables -D INPUT -s %s -j DROP || true" % (ip))
                self.host.execdom0("iptables -D OUTPUT -d %s -j DROP || true" % (ip))
            except:
                pass
        _TC8159.postRun(self)


class TC9028(_MultipathFailureSmoketest):
    """Multipathing failure smoketest using NetApp SR (4 paths)"""
    PATHS = 4

    def createSR(self, host):
        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.napp = napp
        sr = xenrt.lib.xenserver.NetAppStorageRepository(host, "xenrtnetapp")
        sr.create(napp,multipathing=True)
        return sr

class TC9029(TC9028):
    """Multipathing failure smoketest using NetApp SR (2 paths)"""
    PATHS = 2
class TC9767(_MultipathFailureSmoketest):
    """Multipathing failure smoketest using CVSM SR (4 paths)"""
    PATHS = 4

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.cvsmserver = xenrt.CVSMServer(xenrt.TEC().registry.guestGet("CVSMSERVER"))
        self.sr = xenrt.lib.xenserver.CVSMStorageRepository(self.host,
                                                                 "cslgsr")
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        self.napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.cvsmserver.addStorageSystem(self.napp)
        self.sr.create(self.cvsmserver,
                       self.napp,
                       protocol="iscsi",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC9768(TC9767):
    """Multipathing failure smoketest using CVSM SR (2 paths)"""
    PATHS = 2

class TC12901(TC9767):
    """Multipathing failure smoketest using CVSM SR (4 paths)"""
    PATHS = 4

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        self.napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.sr.create(self.napp,
                       protocol="iscsi",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC13992(TC12901):
    """Multipathing failure smoketest using CVSM SR (4 paths)"""
    PATHS = 4

    def createSR(self, host):
        self.host = self.getDefaultHost()
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_EQL_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_EQL_MAXSIZE", 1000000))
        eqlt = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
        self.napp = eqlt # This also has a release method
        self.sr.create(self.napp,
                       protocol="iscsi",
                       physical_size=None,
                       multipathing=True)
        return self.sr

class TC9089(_MultipathFailureSmoketest):
    """Multipathing failure smoketest using NetApp SR (4 paths, HTTPS)"""
    PATHS = 4

    def createSR(self, host):
        minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.napp = napp
        sr = xenrt.lib.xenserver.NetAppStorageRepository(host, "xenrtnetapps")
        # Block HTTP traffic to ensure it uses HTTPS
        host.execdom0("iptables -I INPUT -p tcp -m tcp -s %s --dport 80 "
                      "-j DROP" % (napp.getTarget()))
        sr.create(napp,multipathing=True,options="usehttps=true")
        return sr

    def postRun(self):
        try:
            # Remove the firewall rule to avoid breaking other tests
            self.host.execdom0("iptables -D INPUT -p tcp -m tcp -s %s "
                               "--dport 80 -j DROP || true" % (self.napp.getTarget()))
        except:
            pass
        _MultipathFailureSmoketest.postRun(self)
        

class TC9090(TC9089):
    """Multipathing failure smoketest using NetApp SR (2 paths, HTTPS)"""
    PATHS = 2

class _TC8233(xenrt.TestCase):
    """Base class for TC-8233 style testcases"""
    USE_MANAGEMENT = True
    MPP_RDAC = False

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.targetHost = None
        self.target = None
        self.master = None
        self.slave = None
        self.pool = None
        self.sruuid = None
        self.scsiid = None
        self.lun = None
        self.subnets = []

    def prepare(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        if self.USE_MANAGEMENT:
            netConfig = """<NETWORK>
<PHYSICAL network="NPRI">
<NIC/>
<MANAGEMENT/>
<VMS/>
</PHYSICAL>
<PHYSICAL network="NSEC">
<NIC/>
<VLAN network="VU01">
  <STORAGE/>
</VLAN>
</PHYSICAL>
</NETWORK>"""
        else:
            netConfig = """<NETWORK>
<PHYSICAL network="NPRI">
<NIC/>
<MANAGEMENT/>
<VMS/>
</PHYSICAL>
<PHYSICAL network="NPRI">
<NIC/>
<VLAN network="VU02">
  <STORAGE/>
</VLAN>
</PHYSICAL>
<PHYSICAL network="NSEC">
<NIC/>
<VLAN network="VU01">
  <STORAGE/>
</VLAN>
</PHYSICAL>
</NETWORK>"""

        if not self.MPP_RDAC:
            # 1. Configure a dual-homed iSCSI target spanning NPRI and NSEC
            self.targetHost = self.getHost("RESOURCE_HOST_2")
            self.targetHost.resetToFreshInstall()
            if self.USE_MANAGEMENT:
                vl = self.targetHost.getVLAN("VU01")
                self.subnets.append((vl[1],vl[2]))
                nps = xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNET"])
                npsm = xenrt.TEC().lookup(["NETWORK_CONFIG", "DEFAULT", "SUBNETMASK"])
                self.subnets.append((nps, npsm))
            else:
                vl = self.targetHost.getVLAN("VU01")
                self.subnets.append((vl[1],vl[2]))
                vl = self.targetHost.getVLAN("VU02")
                self.subnets.append((vl[1],vl[2]))

            self.targetHost.createNetworkTopology(netConfig)
            self.target = self.targetHost.createGenericLinuxGuest()
            # Add an interface on the NSEC VLAN
            nworks = self.targetHost.minimalList("network-list")
            vlanBridge = None
            for nw in nworks:
                if "VU01" in self.targetHost.genParamGet("network", nw, "name-label"):
                    vlanBridge = self.targetHost.genParamGet("network", nw, "bridge")
                    break
            self.target.createVIF(eth="eth1", bridge=vlanBridge)
            self.target.plugVIF("eth1")
            time.sleep(5)
            self.target.execguest("echo 'auto eth1' >> "
                                  "/etc/network/interfaces")
            self.target.execguest("echo 'iface eth1 inet dhcp' >> "
                                  "/etc/network/interfaces")
            self.target.execguest("ifup eth1")

            self.initiator = "xenrt-test"
            self.targetiqn = self.target.installLinuxISCSITarget()
            self.targetip = self.target.getIP()
            self.target.createISCSITargetLun(0, 1024)
            self.paths = 2

            if not self.USE_MANAGEMENT:
                # Switch it to use VU02 rather than NPRI for eth0...
                self.target.preCloneTailor() # Needed so new eth0 remains...
                self.target.shutdown()
                self.target.removeVIF("eth0")
                nworks = self.targetHost.minimalList("network-list")
                vlanBridge = None
                for nw in nworks:
                    if "VU02" in self.targetHost.genParamGet("network", nw, "name-label"):
                        vlanBridge = self.targetHost.genParamGet("network", nw, "bridge")
                        break
                self.target.createVIF(eth="eth0", bridge=vlanBridge)
                self.target.start()
                self.targetip = self.target.getIP()
                self.target.execguest("/etc/init.d/iscsi-target start")
        else:
            self.paths = 4

        # 2. Configure two hosts to each have the management interface in NPRI
        #    and storage on NSEC
        # 3. Set up the hosts in a pool with a multipathed LVMoISCSI SR
        self.master = self.getHost("RESOURCE_HOST_0")
        m = self.master
        self.slave = self.getHost("RESOURCE_HOST_1")
        s = self.slave

        m.resetToFreshInstall()
        s.resetToFreshInstall()
        self.pool = xenrt.lib.xenserver.poolFactory(m.productVersion)(m)

        # Configure networking on the master
        m.createNetworkTopology(netConfig)
        # Wait 1 minute to allow for STP issues
        time.sleep(60)

        # Add the SR
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(m, "_TC8233", thinprov)
        if not self.MPP_RDAC:
            self.lun = xenrt.ISCSILunSpecified("%s/%s/%s" %
                                          (self.initiator,
                                           self.targetiqn,
                                           self.targetip))
        else:
            self.lun = xenrt.ISCSILun(minsize=50,mpprdac=True)
            self.initiator = self.lun.getInitiatorName()
            self.targetiqn = self.lun.getTargetName()
            self.targetip = self.lun.getServer()
            self.lunid = self.lun.getID()
        sr.create(self.lun, subtype="lvm", findSCSIID=(not self.MPP_RDAC),
            multipathing=True, mpp_rdac=self.MPP_RDAC)
        self.pool.addSRToPool(sr)
        self.sruuid = sr.uuid
        pbd = m.parseListForUUID("pbd-list",
                                 "sr-uuid",
                                 self.sruuid,
                                 "host-uuid=%s" % (m.getMyHostUUID()))
        self.scsiid = m.genParamGet("pbd", pbd, "device-config", "SCSIid")
        # Join the slave
        self.pool.addHost(s)
        s.addIPConfigToNetworkTopology(netConfig)
        # Wait 1 minute to allow for STP issues
        time.sleep(60)
        # Re-plug the PBD so it picks up both paths straight away
        pbd = s.parseListForUUID("pbd-list",
                                 "sr-uuid",
                                 self.sruuid,
                                 "host-uuid=%s" % (s.getMyHostUUID()))
        cli = s.getCLIInstance()
        cli.execute("pbd-unplug", "uuid=%s" % (pbd))
        cli.execute("pbd-plug", "uuid=%s" % (pbd))
        time.sleep(5)

        # 4. Verify both hosts are using both paths to the target
        self.checkPathCount(m)
        self.checkPathCount(s)

    def run(self, arglist=None):
        # 5. Reboot the slave
        self.slave.reboot()
        # Wait for it to be enabled
        self.slave.waitForEnabled(300)
        # 6. Verify the slave is using both paths to the target
        self.checkPathCount(self.slave)

        # 7. Reboot the master
        self.master.reboot()
        # Wait for it to be enabled
        self.master.waitForEnabled(300)
        # 8. Verify the master is using both paths to the target
        self.checkPathCount(self.master)

    def checkPathCount(self, host):
        # Get the current path count
        if not self.MPP_RDAC:
            mpdevs = host.getMultipathInfo(onlyActive=True)
            if not mpdevs.has_key(self.scsiid):
                raise xenrt.XRTFailure("No multipath info found for our SCSI ID",
                                       "ID %s, info %s" %
                                       (self.scsiid, str(mpdevs)))
            if len(mpdevs[self.scsiid]) != self.paths:
                raise xenrt.XRTFailure("Only found %u/%u paths active on %s" % 
                                       (len(mpdevs[self.scsiid]), self.paths, host.getName()))
        else:
            mpdevs, mppaths = host.getMultipathInfoMPP(onlyActive=True)
            if not mpdevs.has_key(self.scsiid):
                raise xenrt.XRTFailure("No multipath info found for our SCSI ID",
                                       "ID %s, info %s" %
                                       (self.scsiid, str(mpdevs)))
            if mppaths[self.scsiid] != self.paths:
                raise xenrt.XRTFailure("Only found %u/%u paths active on %s" % 
                                       (mppaths[self.scsiid], self.paths, host.getName()))
        # Check the PBD count agrees
        pbd = host.parseListForUUID("pbd-list",
                                    "sr-uuid",
                                    self.sruuid,
                                    "host-uuid=%s" % (host.getMyHostUUID()))
        counts = host.getMultipathCounts(pbd, self.scsiid)
        if counts[0] != self.paths:
            raise xenrt.XRTFailure("PBD record only showed %u/%u paths active "
                                   "on %s" % (counts[0], self.paths, host.getName()))

        if not self.MPP_RDAC:
            # Check the connections are from the correct source ips
            nsdata = host.execdom0("netstat -na | grep :3260 | grep ESTABLISHED")
            foundSubnets = []
            for ns in nsdata.splitlines():
                fields = ns.split()
                source = fields[3].split(":")[0]
                dest = fields[4].split(":")[0]
                # Figure out which subnet this is
                for s in self.subnets:
                    prefixlen = xenrt.util.maskToPrefLen(s[1])
                    destsn = xenrt.util.formSubnet(dest, prefixlen)
                    if destsn == s[0]:
                        # Found the subnet, check the source is in this subnet
                        foundSubnets.append(s)
                        sourcesn = xenrt.util.formSubnet(source, prefixlen)
                        if sourcesn != s[0]:
                            raise xenrt.XRTError("Connection appears to be routed "
                                                 "between subnets", data=ns)
                        break
            if len(foundSubnets) != len(self.subnets):
                raise xenrt.XRTError("Found %u/%u subnets!" % (len(foundSubnets),
                                                               len(self.subnets)))

    def postRun(self):
        if self.lun:
            self.lun.release()

class TC8233(_TC8233):
    """Multipathed iSCSI SR reconnection after host reboot (one path on
       management)"""
    pass

class TC10792(TC8233):
    """Multipathed iSCSI SR reconnection after host reboot (one path on
       management) - MPP"""
    MPP_RDAC = True

class TC8234(_TC8233):
    """Multipathed iSCSI SR reconnection after host reboot (neither path on
       management)"""
    USE_MANAGEMENT = False

class TC10793(TC8234):
    """Multipathed iSCSI SR reconnection after host reboot (neither path on
       management) - MPP"""
    MPP_RDAC = True
    
class TC9084(xenrt.TestCase):
    """Test interaction of multipathing and HA"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.lun = None

    def prepare(self, arglist=None):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        # We should have one host, and one pool available
        # Both should have 4 paths available (NPRI, NSEC, VR01 (on NPRI),
        # and VR02 (on NSEC))
        self.targetHost = self.getHost("RESOURCE_HOST_0")
        self.pool = self.getDefaultPool()

        # Set up an iscsi target on the single host to use for the statefile
        nfs = xenrt.NFSDirectory()
        xenrt.getTestTarball("apiperf", extract=True, directory=nfs.path())
        self.targetHost.createISOSR(nfs.getMountURL("apiperf"))
        self.isosr = self.targetHost.parseListForUUID("sr-list",
                                                      "name-label",
                                                      "Remote ISO Library on: %s" %
                                                      (nfs.getMountURL("apiperf")))
        for s in self.targetHost.getSRs(type="iso", local=True):
            self.targetHost.getCLIInstance().execute("sr-scan", "uuid=%s" %(s))
        time.sleep(30)

        self.target = self.targetHost.createGenericEmptyGuest()
        # Add a disk which will be exported
        self.target.createDisk(sizebytes=10737418240)
        # Add VIFs on the appropriate networks
        secnetworks = self.targetHost.minimalList("network-list")
        eIndex = 0
        for n in secnetworks:
            bridge = self.targetHost.genParamGet("network", n, "bridge")
            try:
                if self.targetHost.genParamGet("network", n, "other-config",
                                               "is_guest_installer_network") == "true":
                    continue
            except:
                # We get an exception if the is_guest_installer_network key
                # doesn't exist...
                pass
            # See if the PIF associated with this network has an IP on
            pif = self.targetHost.minimalList("pif-list", args="network-uuid=%s" % (n))[0]
            if self.targetHost.genParamGet("pif", pif, "IP-configuration-mode") == "None":
                continue
            self.target.createVIF(eth="eth%u" % (eIndex), bridge=bridge)
            eIndex += 1
        if eIndex < 4:
            raise xenrt.XRTError("Only found %u active PIFs on the target "
                                 "host (expecting 4)" % (eIndex))
        elif eIndex > 4:
            raise xenrt.XRTError("Found %u active PIFs on the target host "
                                 "(expecting 4)" % (eIndex))



        # Insert the iscsi target ISO
        self.target.changeCD("xenserver-iscsi-target.iso")

        # Turn the guest in to a PV guest
        self.target.paramSet("PV-bootloader", "pygrub")
        self.target.paramSet("HVM-boot-policy", "")
        #Device         xvdd    xvda
        #User device    3       0
        vbd = self.target.getDiskVBDUUID("3")
        self.targetHost.genParamSet("vbd", vbd, "bootable", "true") 

        # Start it (can't use the normal start method)
        self.target.lifecycleOperation("vm-start")
        # Wait for the VM to come up.
        xenrt.TEC().progress("Waiting for the VM to enter the UP state")
        self.target.poll("UP", pollperiod=5)

        # Now retrieve IP addresses
        tries = 0
        while True:
            try:
                mac, ip, vbridge = self.target.getVIF("eth0")
                if ip:
                    break
            except:
                pass
            if tries == 10:
                raise xenrt.XRTError("Unable to initialise iscsi target VM")
            time.sleep(30)

        time.sleep(10) # Just to make sure all interfaces are up

        self.targetIPs = {}
        for i in range(4):
            mac, ip, vbridge = self.target.getVIF("eth%u" % (i))
            self.targetIPs[i] = ip

        # Only do the blocks on 1 of the 3 hosts in the pool
        self.blockHost = self.pool.getHosts()[1]

        # Now add an iSCSI SR to the pool, and enable HA on it
        # Set up the SR on the host
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.pool.master,
                                                             "HA_Multipath", thinprov)
        # IQN will be iqn.2008-09.com.xensource:<vm_uuid>
        iqn = "iqn.2008-09.com.xensource:%s" % (self.target.getUUID())
        
        self.lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s/1" %
                                      (iqn, self.targetIPs[0]))
        for h in self.pool.getHosts():
            h.enableMultipathing()

        sr.create(self.lun, subtype="lvm", findSCSIID=True, multipathing=True)
        pbd = self.pool.master.parseListForUUID("pbd-list",
                                                "sr-uuid",
                                                sr.uuid,
                                                "host-uuid=%s" %
                                                (self.pool.master.getMyHostUUID()))
        self.pbd = pbd
        self.scsiID = self.pool.master.genParamGet("pbd", pbd, "device-config", "SCSIid")

        # Enable HA
        self.pool.enableHA(srs=[sr.uuid])
        # Check it's stable in this state
        self.checkPathCounts(4)

        # Create a single protected VM on the SR
        self.guest = self.pool.master.createGenericLinuxGuest(sr=sr.uuid)
        self.guest.setHAPriority("2")

    def run(self, arglist=None):
        # These operations are deliberately done sequentially rather than using
        # subcases, as if a host fences, we won't easily be able to recover anyway

        # Pre-determined operations
        xenrt.TEC().logdelimit("Beginning pre-determined operations")

        # Block each path in turn
        xenrt.TEC().logverbose("Blocking paths 1 at a time...")
        for i in range(4):
            xenrt.TEC().logverbose("Blocking path %u" % (i))
            self.iptables(i, True)
            time.sleep(50)            
            # Make sure the block has been seen
            self.checkPathCounts(3)
            # Wait 2 mins to see if any hosts fence
            time.sleep(120)
            self.pool.checkHA()
            # Check no reboots have happened
            self.checkAllHostsUptime()        
            # Restore the path
            xenrt.TEC().logverbose("Restoring path %u" % (i))
            self.iptables(i, False)
            # Wait 1 minute to make sure the block clears properly
            time.sleep(60)
            self.checkPathCounts(4)
        xenrt.TEC().logverbose("...done")

        # Block 2 paths at a time
        xenrt.TEC().logverbose("Blocking paths 2 at a time...")
        for i in range(0,4,2):
            xenrt.TEC().logverbose("Blocking paths %u+%u" % (i,i+1))
            self.iptables(i, True)
            self.iptables(i+1, True)
            time.sleep(50)
            # Make sure the block has been seen
            self.checkPathCounts(2, atLeast=3)
            # Wait 2 mins to see if any hosts fence
            time.sleep(60)
            self.checkPathCounts(2)
            time.sleep(60)
            self.pool.checkHA()
            # Check no reboots have happened
            self.checkAllHostsUptime()
            # Restore the path
            xenrt.TEC().logverbose("Restoring paths %u+%u" % (i,i+1))
            self.iptables(i, False)
            self.iptables(i+1, False)
            # Wait 1 minute to make sure the block clears properly
            time.sleep(60)
            self.checkPathCounts(4)
        xenrt.TEC().logverbose("...done")

        # Block 3 paths at a time
        xenrt.TEC().logverbose("Blocking paths 3 at a time...")
        xenrt.TEC().logverbose("Blocking paths 0+1+2")
        self.iptables(0, True)
        self.iptables(1, True)
        self.iptables(2, True)
        time.sleep(50)
        # Make sure the block has been seen
        self.checkPathCounts(1, atLeast=3)
        # Wait 2 mins to see if any hosts fence
        time.sleep(60)
        self.checkPathCounts(1)
        time.sleep(60)
        self.pool.checkHA()
        # Check no reboots have happened
        self.checkAllHostsUptime()
        # Restore the path
        xenrt.TEC().logverbose("Restoring paths 0+1+2")
        self.iptables(0, False)
        self.iptables(1, False)
        self.iptables(2, False)
        # Wait 1 minute to make sure the block clears properly
        time.sleep(60)
        self.checkPathCounts(4)
        xenrt.TEC().logverbose("...done")

        # Simulate a failed path swap (i.e. block 3 paths, wait, then unblock 1 and immediately block another)
        xenrt.TEC().logverbose("Simulating failed path swap...")
        self.iptables(0, True)
        self.iptables(1, True)
        self.iptables(2, True)
        time.sleep(50)
        # Make sure the block has been seen
        self.checkPathCounts(1, atLeast=3)
        # Wait 2 mins to see if any hosts fence
        time.sleep(60)
        self.checkPathCounts(1)
        time.sleep(60)
        self.pool.checkHA()
        # Check no reboots have happened
        self.checkAllHostsUptime()
        # Restore one path, and immediately block the current working one
        self.iptables(1, False)
        self.iptables(3, True)
        time.sleep(50)
        # Make sure the block has been seen
        self.checkPathCounts(1)
        # Wait 2 mins to see if any hosts fence
        time.sleep(120)
        self.pool.checkHA()
        # Check no reboots have happened
        self.checkAllHostsUptime()
        # Unblock
        self.iptables(0, False)
        self.iptables(2, False)
        self.iptables(3, False)        
        xenrt.TEC().logverbose("...done")
           
        xenrt.TEC().logdelimit("Beginning random operations")
        # Random operations
        pathsBlocked = []        
        for i in range(15): # 15 operations should be ~45 mins
            # Do we have any paths blocked
            if len(pathsBlocked) > 0:
                # Do we have to unblock
                if len(pathsBlocked) == 3:
                    ub = random.randint(0, 2)
                    ubp = pathsBlocked[ub]
                    xenrt.TEC().logverbose("Unblocking path %u" % (ubp))
                    self.iptables(ubp, False)
                    pathsBlocked.remove(ubp)
                # Decide whether to unblock, or block another 1
                if random.randint(0, 1) == 1:
                    # Block another
                    options = [0, 1, 2, 3]
                    for x in pathsBlocked:
                        options.remove(x)
                    b = random.randint(0, len(options)-1)
                    bp = options[b]
                    xenrt.TEC().logverbose("Blocking path %u" % (bp))
                    self.iptables(bp, True)
                    pathsBlocked.append(bp)
                else:
                    # Unblock
                    ub = random.randint(0, len(pathsBlocked)-1)
                    ubp = pathsBlocked[ub]
                    xenrt.TEC().logverbose("Unblocking path %u" % (ubp))
                    self.iptables(ubp, False)
                    pathsBlocked.remove(ubp)
            else:
                # Block a path at random
                options = [0, 1, 2, 3]
                b = random.randint(0, len(options)-1)
                bp = options[b]
                self.iptables(bp, True)
                pathsBlocked.append(bp)

            xenrt.TEC().logverbose("Verifying hosts are OK")
            time.sleep(110)
            self.checkPathCounts(4-len(pathsBlocked))
            time.sleep(60)
            self.pool.checkHA()
            self.checkAllHostsUptime()

        xenrt.TEC().logverbose("Random operations complete")

    def iptables(self, path, block):
        cmd = "iptables "
        if block:
            cmd += "-I "
        else:
            cmd += "-D "
        cmd += "INPUT -s %s -j DROP" % (self.targetIPs[path])
        self.blockHost.execdom0(cmd)

    def checkPathCount(self, host, expected, atLeast=None):
        mp = host.getMultipathInfo()
        if len(mp[self.scsiID]) != 4:
            raise xenrt.XRTFailure("Total path count %u, expecting 4" %
                                   (len(mp[self.scsiID])))
        amp = host.getMultipathInfo(onlyActive=True)
        if len(amp[self.scsiID]) != expected:
            # If we are seeing more paths active, then see if we see 'atLeast'
            if atLeast and len(amp[self.scsiID]) > expected:
                if len(amp[self.scsiID]) <= atLeast:
                    xenrt.TEC().warning("%u paths active when expecting %u" % (len(amp[self.scsiID]), expected))
                    return
            raise xenrt.XRTFailure("Active path count %u, expecting %u" %
                                   (len(amp[self.scsiID]), expected))            

    def checkPathCounts(self, expected, atLeast=None):
        for h in self.pool.getHosts():
            if h != self.blockHost:
                self.checkPathCount(h, 4)
            else:
                self.checkPathCount(h, expected, atLeast=atLeast)

    def checkAllHostsUptime(self):
        for h in self.pool.getHosts():
            try:
                uptime = h.execdom0("uptime")
            except:
                raise xenrt.XRTFailure("Unable to get uptime from host %s, has "
                                       "it self fenced?" % (h.getName()))

            r = re.search(r"up (\d+) min", uptime)
            if r and int(r.group(1)) <= 10:
                raise xenrt.XRTFailure("Host %s appears to have self fenced "
                                       "during multipath failover" % (h.getName()),
                                       data=uptime)    

    def postRun(self):
        if self.lun:
            self.lun.release()


class TC9086(testcases.xenserver.tc.vhd._LVHDPerformance):
    """Verify multipathing has minimal overhead on data path performance"""
    TEST = [1]
    ITERATIONS = 10
    MARGIN = 0 # We expect to run on a NetApp which supports multiple aggregated
               # paths, so we expect a performance improvement (and require no
               # degradation)
    PATHS = 4 # Number of paths we expect to see

    def prepare(self, arglist):
        testcases.xenserver.tc.vhd._LVHDPerformance.prepare(self, arglist)        

        self.path = "/mnt/raw"
        self.maketarget(self.path, self.guest, raw=True)

        # Ensure multipathing is turned off initially

        # Shut down the VM, and re-plug PBDs
        self.guest.shutdown()
        sr = self.host.lookupDefaultSR()
        # See if this is a NetApp SR (i.e. LUN-per-VDI)
        srtype = self.host.genParamGet("sr", sr, "type")
        lunpervdi = (srtype == "netapp" or srtype == "equal")
        self.pbd = self.host.minimalList("pbd-list", args="sr-uuid=%s" % (sr))[0]
        cli = self.host.getCLIInstance()
        cli.execute("pbd-unplug", "uuid=%s" % (self.pbd))
        self.host.disableMultipathing()
        cli.execute("pbd-plug", "uuid=%s" % (self.pbd))
        self.guest.start()
        if lunpervdi:
            vdi = self.guest.getDiskVDIUUID("2")
            self.scsiid = self.host.genParamGet("vdi", vdi, "sm-config", "SCSIid")
        else:
            self.scsiid = self.host.genParamGet("pbd", self.pbd, "device-config", "SCSIid")

    def run(self, arglist):
        self.tests = [0, 1, 2] # Sequential+random read+write performance
        self.target = self.guest
        self.iterations = self.ITERATIONS

        # First without multipathing
        self.runSubcase("testrun", "single", "MultiPerf", "single")

        # Now with multipathing
        self.guest.shutdown()
        cli = self.host.getCLIInstance()
        cli.execute("pbd-unplug", "uuid=%s" % (self.pbd))
        self.host.enableMultipathing()
        cli.execute("pbd-plug", "uuid=%s" % (self.pbd))
        self.guest.start()
        # Check we have the right number of paths
        mp = self.host.getMultipathInfo()
        if len(mp[self.scsiid]) != self.PATHS:
            raise xenrt.XRTError("Expecting %u paths, found %u" %
                                 (self.PATHS, len(mp[self.scsiid])))

        self.runSubcase("testrun", "multi", "MultiPerf", "multi")

        self.compare("single", "multi")
        self.report("single/multi")
        self.checkMargins("single/multi")

    def isRaw(self, vdiuuid):
        # We're using NetApp, so the VDI is automatically raw...
        return True

class TC9087(xenrt.TestCase):
    """Verify multipathing has minimal overhead on control path performance"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        # We assume we have the NetApp SR already set up for us by the sequence
        # Ensure multipathing is enabled
        sr = self.host.lookupDefaultSR()
        self.pbd = self.host.minimalList("pbd-list", args="sr-uuid=%s" % (sr))[0]
        cli = self.host.getCLIInstance()
        cli.execute("pbd-unplug", "uuid=%s" % (self.pbd))
        self.host.enableMultipathing()
        cli.execute("pbd-plug", "uuid=%s" % (self.pbd))

        # Create a VM
        self.guest = self.host.createGenericLinuxGuest()
        
        # Create 30 VDIs, and 10 VBDs on the VM
        self.vdis = []
        for i in range(30):
            self.vdis.append(self.host.createVDI(sizebytes=10485760))

    def run(self, arglist):
        # Start a timer so we can provide feedback on each loop
        timer = xenrt.util.Timer()        

        cli = self.host.getCLIInstance()

        # Measure the overall time as well
        startTime = xenrt.util.timenow()
        for i in range(50):
            xenrt.TEC().logdelimit("Starting loop iteration %u" % (i))
            timer.startMeasurement()
            for j in range(3):
                startIndex = j * 10
                vbds = []
                for k in range(10):
                    vbd = self.guest.createDisk(vdiuuid=self.vdis[startIndex+k],
                                                returnVBD=True)
                    vbds.append(vbd)
                for vbd in vbds:
                    cli.execute("vbd-unplug", "uuid=%s" % (vbd))
                    cli.execute("vbd-destroy", "uuid=%s" % (vbd))
            timer.stopMeasurement()
        stopTime = xenrt.util.timenow()

        overallTime = stopTime - startTime
        xenrt.TEC().value("overall", overallTime)
        xenrt.TEC().value("minTime", timer.min())
        xenrt.TEC().value("maxTime", timer.max())
        xenrt.TEC().value("mean", timer.mean())
        xenrt.TEC().value("stddev", timer.stddev())

        # TODO: Decide of the overall time was acceptable or not...

class TC9088(xenrt.TestCase):
    """Verify multipathing alert functionality"""
    TESTS = ["checkNoActivity", "checkMasterFailover", "findSyncPoint",
             "checkSinglePath", "checkMultipleFailures", "checkFlapping",
             "checkMultipleChanging"]

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.lun = None

    def prepare(self, arglist=[]):
        # Parse argument to check this is thin provisioning test.
        thinprov = self.checkArgsKeyValue(arglist, "thin", "yes")

        # We should have one host, and one pool available
        # Both should have 4 paths available (NPRI, NSEC, VR01 (on NPRI),
        # and VR02 (on NSEC))
        self.targetHost = self.getHost("RESOURCE_HOST_0")
        self.pool = self.getDefaultPool()

        # Set up an iscsi target on the single host to use for the statefile
        self.target = self.targetHost.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.target)
        secnetworks = self.targetHost.minimalList("network-list")
        eIndex = 1
        self.targetIPs = {0:self.target.getIP()}
        for n in secnetworks:
            bridge = self.targetHost.genParamGet("network", n, "bridge")
            xenrt.TEC().logverbose("Considering %s for the second NIC" %
                                   (bridge))
            try:
                if bridge == self.targetHost.getPrimaryBridge():
                    xenrt.TEC().logverbose("Not using %s because it is the "
                                           "primary bridge " %
                                           (bridge))
                    continue
                if self.targetHost.genParamGet("network", n, "other-config",
                                               "is_guest_installer_network") == "true":
                    xenrt.TEC().logverbose("Not using %s because it is the "
                                           "guest installer network " %
                                           (bridge))
                    continue
            except:
                # We get an exception if the is_guest_installer_network key
                # doesn't exist...
                pass
            # See if the PIF associated with this network has an IP on
            pif = self.targetHost.minimalList("pif-list", args="network-uuid=%s" % (n))[0]
            if self.targetHost.genParamGet("pif", pif, "IP-configuration-mode") == "None":
                xenrt.TEC().logverbose("Not using %s because it has no IP " %
                                       (bridge))
                continue
            # Skip if this is the same network as the primary network
            ip = self.targetHost.genParamGet("pif", pif, "IP")
            subnet, netmask = self.targetHost.getNICNetworkAndMask(0)
            if xenrt.util.isAddressInSubnet(ip, subnet, netmask):
                xenrt.TEC().logverbose("Not using %s because it is in the "
                                       "same subnet as the primary NIC" %
                                       (bridge))
                continue
            
            self.target.createVIF(eth="eth%u" % (eIndex), bridge=bridge,
                                  plug=True)
            time.sleep(5)
            self.target.execguest("echo 'auto eth%u' >> "
                                  "/etc/network/interfaces" % (eIndex))
            self.target.execguest("echo 'iface eth%u inet dhcp' >> "
                                  "/etc/network/interfaces" % (eIndex))
            self.target.execguest("echo 'post-up route del -net default dev "
                                  "eth%u' >> /etc/network/interfaces" % (eIndex))
            self.target.execguest("ifup eth%u" % (eIndex))

            # Retrieve IP address
            ip = self.target.execguest("ifconfig eth%u | grep \"inet addr:\"" % (eIndex))
            ip = ip.split()[1].split(":")[1]
            self.targetIPs[eIndex] = ip
            eIndex += 1
        if eIndex < 4:
            raise xenrt.XRTError("Only found %u active PIFs on the target "
                                 "host (expecting 4)" % (eIndex))
        elif eIndex > 4:
            raise xenrt.XRTError("Found %u active PIFs on the target host "
                                 "(expecting 4)" % (eIndex))

        self.getLogsFrom(self.target)

        # Set up the iSCSI target
        iqn = self.target.installLinuxISCSITarget()
        self.target.createISCSITargetLun(0, 1024)

        # Now add an iSCSI SR to the pool, and enable HA on it
        # Set up the SR on the host
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.pool.master,
                                                             "HA_Multipath", thinprov)
        self.sr = sr
        self.lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" %
                                      (iqn, self.target.getIP()))
        for h in self.pool.getHosts():
            h.enableMultipathing()

        sr.create(self.lun, subtype="lvm", findSCSIID=True, multipathing=True)
        pbd = self.pool.master.parseListForUUID("pbd-list",
                                                "sr-uuid",
                                                sr.uuid,
                                                "host-uuid=%s" %
                                                (self.pool.master.getMyHostUUID()))
        self.pbd = pbd
        self.scsiID = self.pool.master.genParamGet("pbd", pbd, "device-config", "SCSIid")
        self.messages = self.pool.master.minimalList("message-list")

        self.syncPoint = None

    def run(self, arglist):
        # Each subcase can run independently, so even if one fails, continue
        # running the others
        for t in self.TESTS:
            self.runSubcase(t, (), "MultiAlert", t)
            # Display all messages to help with debugging
            cli = self.pool.getCLIInstance()
            cli.execute("message-list")
            # Clean up
            xenrt.TEC().logverbose("Removing any leftover firewall rules")
            for h in self.pool.getHosts():
                for i in range(4):
                    h.execdom0("iptables -D INPUT -s %s -j DROP || true" % (self.targetIPs[i]))
            self.target.execguest("iptables -D INPUT -i eth1 -p tcp --dport 3260 -j DROP || true")
            xenrt.TEC().logverbose("Waiting 3 minutes to ensure alerts are created for any restoration...")
            time.sleep(180)
            xenrt.TEC().logverbose("...done")
            self.getNewMessages()

    def postRun(self):
        # Clear up the SR
        self.sr.remove()
        if self.lun:
            self.lun.release()

    def checkNoActivity(self):
        # Wait 3 mins and check we have no multipath alerts
        xenrt.TEC().logverbose("Waiting 3 minutes to ensure no spurious "
                               "multipath messages are generated...")
        time.sleep(180)
        xenrt.TEC().logverbose("...done")
        newMessages = self.getNewMessages()
        if len(newMessages) > 0:
            raise xenrt.XRTFailure("Spurious message(s) generated despite no "
                                   "path events occuring...",
                                   data=str(newMessages))

    def findSyncPoint(self):
        host = self.pool.getSlaves()[0]
        host.execdom0("iptables -I INPUT -s %s -j DROP" % (self.targetIPs[0]))
        st = xenrt.util.timenow()
        syncPoint = None
        while (xenrt.util.timenow() - st) < (5 * 60):
            if len(self.getNewMessages()) > 0:
                syncPoint = xenrt.util.timenow()
                break
            time.sleep(1)
        if not syncPoint:
            raise xenrt.XRTFailure("No message generated within 5 minutes")
        self.syncPoint = syncPoint
        xenrt.TEC().logverbose("syncPoint : %s" % self.syncPoint)

    def checkSinglePath(self):
        # Check the simple case (fail a path and make sure we get an alert within 3 minutes)
        self.syncWithDaemon()
        xenrt.TEC().logverbose("Failing single path on all hosts, expecting "
                               "one alert within 3 minutes")
        self.target.execguest("iptables -I INPUT -i eth1 -p tcp --dport 3260 -j DROP")
        time.sleep(180)
        newMessages = self.getNewMessages()
        if len(newMessages) != 1:
            raise xenrt.XRTFailure("%u messages generated when 1 expected "
                                   "after failing single path on all hosts" %
                                   (len(newMessages)))
        # We expect to see 3/4 on each host, with single drop
        expectedEvents = []
        for h in self.pool.getHosts():
            expectedEvents.append((h,3,4))
        self.validateMessage(newMessages[0], expectedEvents, expectedEvents)

        # Restore the path
        self.syncWithDaemon()
        self.target.execguest("iptables -D INPUT -i eth1 -p tcp --dport 3260 -j DROP")
        time.sleep(180)
        newMessages = self.getNewMessages()
        if len(newMessages) != 1:
            raise xenrt.XRTFailure("%u messages generated when 1 expected "
                                   "after restoring single path on all hosts" %
                                   (len(newMessages)))
        # We expect to see a restoration event per host
        expectedEvents = []
        for h in self.pool.getHosts():
            expectedEvents.append((h,4,4))
        self.validateMessage(newMessages[0], expectedEvents, [])

    def checkMultipleFailures(self):
        # Looking at a single host, fail one path, then fail another within
        # 2 minutes
        self.syncWithDaemon()
        xenrt.TEC().logverbose("Failing 2 paths within 2 minutes, expecting one"
                               "alert within 3 minutes of first failure")
        host = self.pool.getSlaves()[0]
        host.execdom0("iptables -I INPUT -s %s -j DROP" % (self.targetIPs[0]))
        time.sleep(60)
        host.execdom0("iptables -I INPUT -s %s -j DROP" % (self.targetIPs[1]))
        time.sleep(120)
        newMessages = self.getNewMessages()
        if len(newMessages) != 1:
            raise xenrt.XRTFailure("%u messages generated when 1 expected "
                                   "after failing two paths on one host" %
                                   (len(newMessages)))
        expectedEvents = [(host, 3, 4), (host, 2, 4)]
        unhealthyPaths = [(host, 2, 4)]
        self.validateMessage(newMessages[0], expectedEvents, unhealthyPaths)

        # Restore the paths
        self.syncWithDaemon()
        host.execdom0("iptables -D INPUT -s %s -j DROP" % (self.targetIPs[0]))
        time.sleep(60)
        host.execdom0("iptables -D INPUT -s %s -j DROP" % (self.targetIPs[1]))
        time.sleep(120)
        newMessages = self.getNewMessages()
        if len(newMessages) != 1:
            raise xenrt.XRTFailure("%u messages generated when 1 expected "
                                   "after restoring two paths on one host" %
                                   (len(newMessages)))
        expectedEvents = [(host, 3, 4), (host, 4, 4)]
        self.validateMessage(newMessages[0], expectedEvents, [])

    def checkFlapping(self):
        host = self.pool.getSlaves()[0]
        # Fail one path, then restore it within 2 minutes
        self.syncWithDaemon()
        xenrt.TEC().logverbose("Failing and restoring 1 path within 2 minutes, "
                               "expecting one alert within 3 minutes")
        host.execdom0("iptables -I INPUT -s %s -j DROP" % (self.targetIPs[0]))
        time.sleep(60)
        host.execdom0("iptables -D INPUT -s %s -j DROP" % (self.targetIPs[0]))
        time.sleep(120)
        newMessages = self.getNewMessages()
        if len(newMessages) != 1:
            raise xenrt.XRTFailure("%u messages generated when 1 expected "
                                   "after failing two paths on one host" %
                                   (len(newMessages)))
        expectedEvents = [(host, 3, 4), (host, 4, 4)]
        self.validateMessage(newMessages[0], expectedEvents, [])

    def checkMultipleChanging(self):
        host = self.pool.getSlaves()[0]
        # Fail one path, then within 2 mins restore it and fail another
        self.syncWithDaemon()
        xenrt.TEC().logverbose("Failing/restoring 1 path, and failing another "
                               "within 2 minutes, expecting one alert")
        host.execdom0("iptables -I INPUT -s %s -j DROP" % (self.targetIPs[0]))
        time.sleep(40)
        host.execdom0("iptables -D INPUT -s %s -j DROP" % (self.targetIPs[0]))
        time.sleep(10)
        host.execdom0("iptables -I INPUT -s %s -j DROP" % (self.targetIPs[1])) 
        time.sleep(120)
        newMessages = self.getNewMessages()
        if len(newMessages) != 1:
            raise xenrt.XRTFailure("%u messages generated when 1 expected "
                                   "after failing two paths on one host" %
                                   (len(newMessages)))
        expectedEvents = [(host, 3, 4), (host, 4, 4), (host, 3, 4)]
        self.validateMessage(newMessages[0], expectedEvents, [(host, 3, 4)])

        # Restore the failed path
        self.syncWithDaemon()
        host.execdom0("iptables -D INPUT -s %s -j DROP" % (self.targetIPs[1]))
        time.sleep(180)
        newMessages = self.getNewMessages()
        if len(newMessages) != 1:
            raise xenrt.XRTFailure("%u messages generated when 1 expected "
                                   "after restoring one path on one host" %
                                   (len(newMessages)))
        expectedEvents = [(host, 4, 4)]
        self.validateMessage(newMessages[0], expectedEvents, [])

    def checkMasterFailover(self):
        # Check things are correct at the moment
        self.checkMpathAlert()

        # Verify a clean failover correctly moves the mpathalert daemon
        xenrt.TEC().logverbose("Checking clean master transition correctly "
                               "moves mpathalert daemon")
        self.pool.designateNewMaster(self.pool.getSlaves()[0])
        self.checkMpathAlert()

        # Verify an emergency mode transition correctly moves the mpathalert
        # daemon
        xenrt.TEC().logverbose("Checking emergency mode transition correctly "
                               "moves mpathalert daemon")
        oldmaster = self.pool.master
        newmaster = self.pool.getSlaves()[0]
        self.pool.master.machine.powerctl.off()
        time.sleep(15)
        self.pool.setMaster(newmaster)
        self.pool.recoverSlaves()
        # Restore the original master (it should automatically become a slave)
        oldmaster.machine.powerctl.on()
        oldmaster.waitForSSH(600)
        time.sleep(60)
        oldmaster.waitForEnabled(240)
        self.pool.check()
        self.checkMpathAlert()        

        # Verify a forced HA failover correctly moves the mpathalert daemon
        xenrt.TEC().logverbose("Checking HA failover correctly moves "
                               "mpathalert daemon")

        blockedHost = None
        try:
            self.pool.enableHA()
            oldmaster = self.pool.master
            blockedHost = self.pool.master
            self.pool.master.blockStatefile() # This should cause the master to fence
            self.pool.findMaster(notCurrent=True, timeout=600)
            # Now wait for the original master to boot back up
            oldmaster.waitForSSH(600)
            time.sleep(60)
            self.pool.check()        
            self.checkMpathAlert()
        finally:
            try:
                self.pool.disableHA()
            except:
                pass
            if blockedHost:
                try:
                    blockedHost.blockStatefile(block=False,ignoreErrors=True)
                    blockedHost.haStatefileBlocked = False
                except:
                    pass

        # Clear out any alerts
        self.getNewMessages()

    def getNewMessages(self):
        messages = self.pool.master.minimalList("message-list")
        newMessages = []
        for m in messages:
            if not m in self.messages:
                newMessages.append(m)
                self.messages.append(m)
        return newMessages

    def syncWithDaemon(self):
        """Synchronise with the mpathalert daemon such that we don't have path
           events traversing the 2 minute cycle"""
        # Find the next 2 minute boundary from the syncpoint
        if not self.syncPoint:
            xenrt.TEC().warning("Sync point not defined!")
            return

        nextSyncPoint = None
        i = 1
        while True:
            n = self.syncPoint + (120 * i)
            if n > xenrt.util.timenow():
                nextSyncPoint = n
                break
            i += 1
        # Sleep until we get to nextSyncPoint
        while True:
            if xenrt.util.timenow() > nextSyncPoint:
                break
            time.sleep(1)
        # Wait an extra 2s to be safe
        xenrt.TEC().logverbose("nextSyncPoint : %s" % nextSyncPoint)
        time.sleep(2)

    def checkMpathAlert(self):
        rc = self.pool.master.execdom0("ps -ef | grep [m]pathalert", retval="code")
        if rc != 0:
            raise xenrt.XRTFailure("mpathalert daemon not running on pool master")
        for h in self.pool.getSlaves():
            rc = h.execdom0("ps -ef | grep [m]pathalert", retval="code")
            if rc == 0:
                raise xenrt.XRTFailure("mpathalert daemon running on pool slave %s" % (h.getName()))

    def validateMessage(self, message, expectedEvents, unhealthyPaths):
        # Check the subject is correct
        subj = self.pool.master.genParamGet("message", message, "name")
        if subj != "MULTIPATH_PERIODIC_ALERT":
            raise xenrt.XRTFailure("Multipath message name incorrect",
                                   data="Found '%s', expecting '"
                                        "MULTIPATH_PERIODIC_ALERT'" % (subj))
        # Get the message body
        body = self.pool.master.genParamGet("message", message, "body")
        # Parse it        
        inEvents = False
        events = []
        inUnhealthy = False
        unhealthy = []
        for l in body.splitlines():
            if l.strip() == "":
                # Ignore blank lines
                continue
            elif l.startswith("Events received during the last"):
                inEvents = True
                inUnhealthy = False
                continue
            elif l.startswith("Unhealthy paths"):
                inUnhealthy = True
                inEvents = False
                continue
            
            if not (inEvents or inUnhealthy):
                raise xenrt.XRTFailure("Unexpected line in multipath alert (out of sections)",
                                       data=l)
            # Is it what we're expecting
            m = re.match("\[\d{8}T\d{2}:\d{2}:\d{2}Z\] host=([\w-]+); host-name=\"[\w-]+\"; pbd=([\w-]+); scsi_id=(\w+); current=(\d); max=(\d)", l)
            if not m:
                raise xenrt.XRTFailure("Unexpected line in multipath alert (in section)",
                                       data=l)
            # Pull out the data we want
            hostUUID = m.group(1)
            pbdUUID = m.group(2)
            scsiID = m.group(3)
            current = int(m.group(4))
            max = int(m.group(5))
            if inEvents:
                events.append((hostUUID, pbdUUID, scsiID, current, max, l))
            else:
                unhealthy.append((hostUUID, pbdUUID, scsiID, current, max, l))

        # Copy the lists in case they are both references to the same list
        expectedEvents = expectedEvents[:]
        unhealthyPaths = unhealthyPaths[:]

        # Check each list
        for ev in events:
            hUUID = ev[0]
            h = self.pool.getHost(hUUID)
            e = (h, ev[3], ev[4])
            if not e in expectedEvents:
                raise xenrt.XRTFailure("Unexpected event found in message",
                                       data=ev[5])
            expectedEvents.remove(e)
        if len(expectedEvents) > 0:
            raise xenrt.XRTFailure("Didn't find %u expected events" %
                                   (len(expectedEvents)),
                                   data=str(expectedEvents))
        for up in unhealthy:
            hUUID = up[0]
            h = self.pool.getHost(hUUID)
            u = (h, up[3], up[4])
            if not u in unhealthyPaths:
                raise xenrt.XRTFailure("Unexpected unhealthy path found in "
                                       "message", data=up[5])
            unhealthyPaths.remove(u)
        if len(unhealthyPaths) > 0:
            raise xenrt.XRTFailure("Didn't find %u unhealthy paths" %
                                   (len(unhealthyPaths)),
                                   data=str(unhealthyPaths))


# MultipathRT testcases written and maintained by the ring 3 team
# ===============================================================
class _MultipathRT(testcases.xenserver.tc._XapiRTBase):
    """Base class for Multipath RT testcases"""
    TYPE = "multipath"

    def extraPrepare(self):
        # Create an ISO SR with the iscsi target ISO in
        nfs = xenrt.NFSDirectory()
        xenrt.getTestTarball("apiperf", extract=True, directory=nfs.path())
        self.host.createISOSR(nfs.getMountURL("apiperf"))
        self.nfsSR = self.host.parseListForUUID("sr-list",
                                                "name-label",
                                                "Remote ISO Library on: %s" %
                                                (nfs.getMountURL("apiperf")))
        self.nfs = nfs
        for s in self.host.getSRs(type="iso", local=True):
            self.host.getCLIInstance().execute("sr-scan", "uuid=%s" % (s))
        time.sleep(30)

    def postRun(self):
        # Get rid of the ISO SR
        try:
            self.host.forgetSR(self.nfsSR)
            self.nfs.remove()
        except:
            pass
        testcases.xenserver.tc._XapiRTBase.postRun(self)

class _NetAppMultipathRT(testcases.xenserver.tc._XapiRTBase):
    """Base class for NetApp Multipath RT testcases"""
    TYPE = "multipath"

    def extraPrepare(self):
        # Set up a NetApp SR
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.napp = napp
        sr = xenrt.lib.xenserver.NetAppStorageRepository(self.host, "xenrtnetapp")
        sr.create(napp)
        self.nappSR = sr.uuid

    def postRun(self):
        # Clean up the SR
        try:
            self.host.destroySR(self.nappSR)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception destroying SR: %s" % (str(e)))
            # Try to forget instead
            try:
                self.host.forgetSR(self.nappSR)
            except Exception,e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception forgetting SR: %s" % (str(e)))
        try:
            self.napp.release()
        except:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception releasing NetApp target")
        testcases.xenserver.tc._XapiRTBase.postRun(self)

class _FCMultipathRT(testcases.xenserver.tc._XapiRTBase):
    """Base class for FC Multipath RT testcases"""
    TYPE = "multipath"

    def extraPrepare(self):
        # Set up a FC SR
        lun = xenrt.HBALun(self.getAllHosts())
        sr = xenrt.lib.xenserver.FCStorageRepository(self.host, "fc")
        sr.create(lun)
        self.fcSR = sr.uuid

    def run(self, arglist):
        iterations = 1
        if arglist and len(arglist) > 0:
            iterations = int(arglist[0])
        for i in range(iterations):
            if iterations > 1:
                xenrt.TEC().logverbose("Starting iteration %u" % (i))
            testcases.xenserver.tc._XapiRTBase.run(self, arglist)

    def postRun(self):
        # Clean up the SR
        try:
            self.host.forgetSR(self.fcSR)
        except:
            pass
        testcases.xenserver.tc._XapiRTBase.postRun(self)

class TC9068(_MultipathRT):
    """Device-mapper table integrity for iSCSI multipath"""
    TCID = 9068
class TC9069(_NetAppMultipathRT):
    """Device-mapper table integrity for NetApp multipath"""
    TCID = 9069
class TC9078(_FCMultipathRT):
    """Device-mapper table integrity for FC multipath"""
    TCID = 9078

class TC9071(_MultipathRT):
    """Path fail-over time on iSCSI multipath"""
    TCID = 9071
class TC9072(_NetAppMultipathRT):
    """Path fail-over time on NetApp multipath"""
    TCID = 9072

class TC9074(_MultipathRT):
    """Alert generation with path flapping"""
    TCID = 9074


class _DellPowerVaultMultipathing(testcases.xenserver.tc._XapiRTBase):
    """Base class for Dell PowerVault ISCSI Multipath Failover testcases"""
    TYPE = "multipath"
    
    def configureStorageNetwork(self):
        # Configure the host network
        primaryNetconfig = self.dell.primaryNetconfig.split(',')
        secondaryNetconfig = self.dell.secondaryNetconfig.split(',')
        netconfig = """<NETWORK>
  <PHYSICAL """
        if primaryNetconfig[0] in ["NPRI", "NSEC", "IPRI", "ISEC"]:
            netconfig += 'network="%s">' % primaryNetconfig[0]
        else:
            netconfig += 'network="NPRI">'
        netconfig += """
    <NIC/>
    <VLAN"""
        if "VR" in primaryNetconfig[1]:
            netconfig += ' network="%s">' % primaryNetconfig[1]
            netconfig += """
      <STORAGE/>
    </VLAN>"""
        else:
            netconfig += """/>"""
        netconfig += """
    <MANAGEMENT/>
  </PHYSICAL>"""
        if primaryNetconfig[0] != secondaryNetconfig[0]:
            netconfig += """<PHYSICAL """
            if secondaryNetconfig[0] in ["NPRI", "NSEC", "IPRI", "ISEC"]:
                netconfig += 'network="%s">' % secondaryNetconfig[0]
            else:
                netconfig += 'network="NPRI">'
            netconfig += """
    <NIC/>
    <VLAN"""
            if "VR" in secondaryNetconfig[1]:
                netconfig += ' network="%s">' % secondaryNetconfig[1]
                netconfig += """
      <STORAGE/>
    </VLAN>"""
            else:
                netconfig += """/>"""
            netconfig += """
    <MANAGEMENT/>
  </PHYSICAL>"""
        netconfig += """
</NETWORK>"""
        
        self.host.createNetworkTopology(netconfig)

    def extraPrepare(self):
        
        # Set up a Dell PowerVault ISCSI SR
        dellISCSILun = xenrt.lib.xenserver.ISCSILun(hwtype="DELL_POWERVAULT", usewildcard=True)
        self.dell = dellISCSILun
        # Configure the host network for obtaining all multipaths
        self.configureStorageNetwork()
        # Enable multipathing on host
        self.host.enableMultipathing()
        # Attach the iscsi SR
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, "xenrtDelliSCSI")
        sr.create(self.dell, subtype="lvm", multipathing=True)
        self.dellSR = sr.uuid
        # Workaround for CA-125486, Don't use commas in /etc/multipath.conf
        self.host.execdom0("sed -i s'/,$//' /etc/multipath.conf")
        self.host.reboot()
        

    def postRun(self):
        # Clean up the SR
        try:
            self.host.destroySR(self.dellSR)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception destroying SR: %s" % (str(e)))
            # Try to forget instead
            try:
                self.host.forgetSR(self.dellSR)
            except Exception,e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().warning("Exception forgetting SR: %s" % (str(e)))
        try:
            self.dell.release()
        except:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception releasing Dell PowerVault target")
        testcases.xenserver.tc._XapiRTBase.postRun(self)

class DellPowerVaultIscsiMultipath(_DellPowerVaultMultipathing):
    """Path fail-over on Dell PowerVault ISCSI multipath"""

    TCID = 21002

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.dellSR = None
        self.guest = None
        self.host = None

    def check(self):
        # Check the periodic read/write script is still running on the VM
        rc = self.guest.execguest("pidof python",retval="code")
        if rc > 0:
            # Get the log
            self.guest.execguest("cat /tmp/rw.log || true")
            raise xenrt.XRTFailure("Periodic read/write script failed")

        try:
            line = ''
            line = self.guest.execguest("tail -n 1 /tmp/rw.log").strip()
            if(len(line) == 0):
                raise xenrt.XRTError("/tmp/rw.log file is empty on first attempt")
            first = int(float(line))
            time.sleep(30)
            line = ''
            line = self.guest.execguest("tail -n 1 /tmp/rw.log").strip()
            if(len(line) == 0):
                raise xenrt.XRTError("/tmp/rw.log file is empty on second attempt")
            next = int(float(line))
            if next == first:
                raise xenrt.XRTFailure("Periodic read/write script has not "
                                       "completed a loop in 30 seconds")

        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTError("Exception checking read/write script progress",
                                 data=str(e))

    def enableDisablePath(self, type, ip):
        # Disable or Enable particular IP via iptables
        prevmpdevs = self.host.getMultipathInfo(onlyActive=True)
        self.host.execdom0("iptables -I INPUT -s %s -j %s" % (ip, type))
        self.host.execdom0("iptables -I OUTPUT -s %s -j %s" % (ip, type))
        # Do poll the multipath status
        deadline = xenrt.util.timenow() + 240
        while xenrt.util.timenow() < deadline:
            currmpdevs = self.host.getMultipathInfo(onlyActive=True)
            if prevmpdevs != currmpdevs:
                return
            xenrt.sleep(10)
        if xenrt.util.timenow() > deadline:
            raise xenrt.XRTError("Multipath -ll status has not changed within 4 minutes")
        

    def _multipathGroupStatus(self,line,group,keyname):
        """Get the multipath -ll output in form of primary and secondary groups
           Group status, 'status':'active or 'status':'enable']
        """
        if re.search("status=active", line):
            group['status'] = 'active'
        else:
            group['status'] = 'enabled'
        group[keyname%2] = []
        return group
    
    def _multipathPathsStatus(self,keyname,primary,secondary,line):
        """Get the multipath -ll output in form of primary and secondary group paths 
           Path status , 0:['sda', 'active'/'failed']
        """
        r = re.search(r"^[| ] [|`]- \S+\s+(\S+)\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)", line)
        if r:
            lr = []
            lr.append(r.group(1))
            lr.append(r.group(2))
            if keyname < 2:
                pass
                primary[keyname%2] = lr
            else:
                pass
                secondary[keyname%2] = lr
            keyname += 1
        return keyname,primary,secondary
        
    def multipathInfo(self):
        # Get the multipath -ll output in form of primary and secondary groups
        # primary = {'status':['active'/'enable'], 0:['sda', 'active'/'failed'], 1:['sdb', 'active'/'failed']}
        # secondary = {'status':['active'/'enable'], 0:['sdc', 'active'/'failed'], 1:['sdd', 'active'/'failed']}
        mp = self.host.execdom0("multipath -ll")
        primary = {}
        secondary = {}
        flag = False
        keyname = 0
        for line in mp.splitlines():
            r = re.search(r"([0-9A-Za-z-_]+) *dm-\d+", line)
            
            if r:
                continue
            r = re.search(r"policy", line)
            
            if r and not flag:
                primary = self._multipathGroupStatus(line,primary,keyname)
                flag = True
            
            elif r and flag:
                secondary = self._multipathGroupStatus(line,secondary,keyname)
                
            if not r:
                keyname,primary,secondary = self._multipathPathsStatus(keyname,primary,secondary,line)
    
        xenrt.TEC().logverbose("Details of primary path are %s and secondary path are %s" % (str(primary), str(secondary)))
        return primary, secondary

    def checkMultipathInfo(self, lunpaths):
        # lunpaths[0] and lunpaths[1] states expected primary paths status
        # lunpaths[2] and lunpaths[3] states expected secondary paths status
        # True for active and False for failed
        xenrt.sleep(10)
        primary, secondary = self.multipathInfo()
        
        if lunpaths[0] and lunpaths[1]:
            if not (primary['status'] == 'active' and primary[0][1] == 'active' and primary[1][1] == 'active'):
                raise xenrt.XRTFailure("Both Primary Paths are not active")
        elif (lunpaths[0] or lunpaths[1]):
            if not (primary['status'] == 'active' and (primary[0][1] == 'active' or primary[1][1] == 'active')):
                raise xenrt.XRTFailure("None of the Primary Paths are active")
        elif not lunpaths[0] and not lunpaths[1] and lunpaths[2] and lunpaths[3]:
            if not (secondary['status'] == 'active' and secondary[0][1] == 'active' and secondary[1][1] == 'active'):
                raise xenrt.XRTFailure("Both Secondary Paths are not active")
        elif not lunpaths[0] and not lunpaths[1] and (lunpaths[2] or lunpaths[3]):
            if not (secondary['status'] == 'active' and (secondary[0][1] == 'active' or secondary[1][1] == 'active')):
                raise xenrt.XRTFailure("None of the Secondary Paths are active")
        elif not lunpaths[0] and not lunpaths[1] and not lunpaths[2] and not lunpaths[3]:
            if not (primary['status'] == 'enabled' and secondary['status'] == 'enabled'):
                if not primary[0][1] == 'failed' and primary[1][1] == 'failed':
                    if not secondary[0][1] == 'failed' and secondary[1][1] == 'failed':
                        raise xenrt.XRTFailure("Atleast one of the Primary or Secondary Path is active")
    
    def run(self, arglist=None):
        
        # Get the multipath IPs for the failover/recover testing
        primaryIPs = self.dell.primaryIPs.split(',')
        secondaryIPs = self.dell.secondaryIPs.split(',')
        lunpath = [True,True,True,True]
        self.checkMultipathInfo(lunpath)
        # Set up VM with VDI on iscsi SR with periodically reading/writing
        self.guest = self.host.createGenericLinuxGuest(name="testVM", sr=self.dellSR)
        dev = self.guest.createDisk(sizebytes=5368709120, sruuid=self.dellSR, returnDevice=True) # 5GB
        xenrt.sleep(30)
        # Launch a periodic read/write script using the new disk
        self.guest.execguest("%s/remote/readwrite.py /dev/%s > /tmp/rw.log "
                             "2>&1 < /dev/null &" %
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), dev))
        xenrt.sleep(30)
        # Check the SR is functional
        self.check()

        # Primary/Secondary Paths Failover Loop
        for i in range(0, 50):
            log("failover/recover loop count is %s " % str(i))
            # Disable 1st primary path
            self.enableDisablePath("DROP", primaryIPs[1])
            lunpath = [False,True,True,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            
            # Disable 2nd primary path
            self.enableDisablePath("DROP", primaryIPs[0])
            lunpath = [False,False,True,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            
            # Disable 1st secondary path
            self.enableDisablePath("DROP", secondaryIPs[1])
            lunpath = [False,False,False,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            
            # Enable 1st primary path
            self.enableDisablePath("ACCEPT", primaryIPs[1])
            lunpath = [True,False,False,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            
            # Enable 2nd primary path
            self.enableDisablePath("ACCEPT", primaryIPs[0])
            lunpath = [True,True,False,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            
            # Enable 1st secondary path
            self.enableDisablePath("ACCEPT", secondaryIPs[1])
            lunpath = [True,True,True,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            
            # Disable both primary paths
            self.enableDisablePath("DROP", primaryIPs[0])
            self.enableDisablePath("DROP", primaryIPs[1])
            lunpath = [False,False,True,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            
            # Enable both primary paths
            self.enableDisablePath("ACCEPT", primaryIPs[0])
            self.enableDisablePath("ACCEPT", primaryIPs[1])
            lunpath = [True,True,True,True]
            self.checkMultipathInfo(lunpath)
            self.check()
            

        # Disable all paths
        self.enableDisablePath("DROP", primaryIPs[0])
        self.enableDisablePath("DROP", primaryIPs[1])
        self.enableDisablePath("DROP", secondaryIPs[0])
        self.enableDisablePath("DROP", secondaryIPs[1])

        lunpath = [False,False,False,False]
        self.checkMultipathInfo(lunpath)

        # Enable all paths
        self.host.execdom0("service iptables restart")
        xenrt.sleep(60)
        # Restart the VM for enabling multipathing
        self.guest.reboot()
        lunpath = [True,True,True,True]
        self.checkMultipathInfo(lunpath)
        

#############################################################################
# FC

class TC15464(xenrt.TestCase):
    """Test the consistency of devices in the multipath group"""

    # CL03 machines configured to have LUNs from both EMC Clariion & PowerVault arrays.
    # However, when used in the test, by default it uses LUNs from PowerVault.
    # CL05 machines are configured to have LUNs from EMC Clariion only.

    def prepare(self, arglist=None):
        pool = self.getDefaultPool()
        if pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = pool.master

        self.no_fc_ports = self.host.getNumOfFCPorts()
        if self.no_fc_ports == 0:
            raise xenrt.XRTError("The host %s is not configured with any fibre channel connections." %
                                                                                                self.host)

        self.host.enableAllFCPorts() # Enable all the FC ports, if not.
        self.host.enableMultipathing() # Enable multipathing on host.

        lun = xenrt.HBALun(self.getAllHosts())
        self.lun0_scsiid = lun.getID()

        self.fc_sr = xenrt.lib.xenserver.FCStorageRepository(self.host, "FC01")
        self.fc_sr.create(lun, multipathing=True)

    def getScsiID(self, dev):
        return self.host.getSCSIID(dev)

    def disableRandomFCPorts(self):
        self.random_fc_ports = []
        while True:
            self.random_fc_ports = random.sample(xrange(self.no_fc_ports), 
                                                 random.randint(0,self.no_fc_ports))
            if len(self.random_fc_ports) > 0:
                break

        for port in self.random_fc_ports:
            self.host.disableFCPort(port)

    def enableFCPorts(self):
        for port in self.random_fc_ports:
            self.host.enableFCPort(port)

    def waitUntilDevicesAreInaccessible(self, timeout=180):
        now = xenrt.util.timenow()
        deadline = now + timeout
        while True:
            try:
                for dev in self.dev_list:
                    self.host.execdom0("sg_inq /dev/%s | grep serial" % dev).strip()
            except:
                break

            now = xenrt.util.timenow()
            if now > deadline:
                raise xenrt.XRTError("Devices are still accessible")
            time.sleep(15)

    def getDevList(self):
        dm_map = self.host.getMultipathInfo()
        curr_dev_list = dm_map[self.lun0_scsiid]
        return curr_dev_list

    def checkWhetherMultipathTopologyHasChanged(self):
        curr_dev_list = set(self.getDevList())
        orig_dev_list = set(self.dev_list)
        
        if not curr_dev_list.issubset(orig_dev_list):
            xenrt.TEC().logverbose("Current devices in multipath map are %s" % curr_dev_list)
            xenrt.TEC().logverbose("Original set of devices were %s" % orig_dev_list)
            raise xenrt.XRTFailure("Unexpected devices found in the multipath map")

        if len(curr_dev_list) == len(orig_dev_list):
            xenrt.TEC().logverbose("Current devices in multipath map are %s" % curr_dev_list)
            xenrt.TEC().logverbose("Original set of devices were %s" % orig_dev_list)
            raise xenrt.XRTFailure("Multipath topology didn't change")

    def checkSanityOfDevs(self):
        curr_dev_list = set(self.getDevList())
        xenrt.TEC().logverbose("Current devices in multipath map are %s" % curr_dev_list)

        incorrect_devs = []
        stale_devs = []
        for dev in curr_dev_list:
            try:
                scsi_id = self.getScsiID(dev)
                if scsi_id != self.lun0_scsiid:
                    incorrect_devs.append(dev) # Disaster
            except:
                # Looks like it's a stale dev entry in the multipath MAP ... equally bad
                stale_devs.append(dev)

        if incorrect_devs:
            xenrt.TEC().logverbose("wrong devices in the multipath group: %s" % incorrect_devs)
        if stale_devs:
            xenrt.TEC().logverbose("stale devices in the multipath group: %s" % stale_devs)
        if incorrect_devs or stale_devs:
            raise xenrt.XRTFailure("Unexpected devices in the multipath group")

    def testMultipathSanity(self):
        self.disableRandomFCPorts()
        xenrt.sleep(180) # wait till devices are disabled.
        self.waitUntilDevicesAreInaccessible()
        xenrt.sleep(3) # handling CA-124429
        self.checkWhetherMultipathTopologyHasChanged()
        self.enableFCPorts()
        xenrt.sleep(180) # wait till devices are accessible
        self.checkSanityOfDevs()
        self.dev_list = self.getDevList() # the devices in the multipath group might change

    def run(self, arglist=None):
        # 1. Let us get the current mapping
        self.dm_map = self.host.getMultipathInfo()

        if not self.dm_map.has_key(self.lun0_scsiid):
            raise xenrt.XRTFailure("Could not find the multipath group for scsiid %s" % 
                                   self.lun0_scsiid)
        self.dev_list = self.dm_map[self.lun0_scsiid]
        for i in range(10):
            self.testMultipathSanity()

    def postRun(self):
        pass

class _HardwareMultipath(xenrt.TestCase):
    """Base class for FC boot-from-san multipath tests"""

    ROOTDISK_MPATH_COUNT = 4
    DEFAULT_PATH_COUNT   = 1

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()
        
        for h in self.pool.getHosts():
            if h.lookup(["FC", "CMD_HBA0_ENABLE"], None) != None and h.lookup(["FC", "CMD_HBA1_ENABLE"], None) != None:
                self.hostWithMultiplePaths = h
                self.scsiid = string.split(h.lookup("OPTION_CARBON_DISKS", None), "scsi-")[1]
                return
        
        raise xenrt.XRTFailure("Could not find host with multiple paths.")

    def disableFCPort(self, port):
        xenrt.TEC().logverbose("Disabling FC Port %u" % port)
        self.hostWithMultiplePaths.disableFCPort(port)
        time.sleep(60)    

        mp = self.hostWithMultiplePaths.getMultipathInfo(onlyActive=True, useLL=True)
        
        if not mp.has_key(self.scsiid):
            raise xenrt.XRTFailure("Expecting %u/%u paths active, found %u, the default path" %
                                        (self.ROOTDISK_MPATH_COUNT/2, self.ROOTDISK_MPATH_COUNT, self.DEFAULT_PATH_COUNT))

        if len(mp[self.scsiid]) > self.ROOTDISK_MPATH_COUNT/2:
            raise xenrt.XRTFailure("Expecting %u/%u paths active, found %u" %
                                        (self.ROOTDISK_MPATH_COUNT/2, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))

        xenrt.TEC().logverbose("Successfully disabled FC Port %u" % port)

    def enableFCPort(self, port):
        xenrt.TEC().logverbose("Enabling FC Port %u" % port)
        self.hostWithMultiplePaths.enableFCPort(port)
        time.sleep(60)    

        mp = self.hostWithMultiplePaths.getMultipathInfo(onlyActive=True, useLL=True)
        
        if not mp.has_key(self.scsiid):
            raise xenrt.XRTFailure("Expecting %u/%u paths active, found %u, the default path" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, self.DEFAULT_PATH_COUNT))

        if len(mp[self.scsiid]) != self.ROOTDISK_MPATH_COUNT:
            raise xenrt.XRTFailure("Expecting %u/%u paths active, found %u" %
                                        (self.ROOTDISK_MPATH_COUNT, self.ROOTDISK_MPATH_COUNT, len(mp[self.scsiid])))

        xenrt.TEC().logverbose("Successfully enabled FC Port %u" % port)
    
    def run(self, arglist=None):
        self.enableFCPort(0)
        self.enableFCPort(1)

        self.lun = xenrt.HBALun([self.hostWithMultiplePaths])

        self.sr_scsiid = self.lun.getID()
        self.sr = xenrt.lib.xenserver.FCStorageRepository(self.hostWithMultiplePaths, "fc")
        self.sr.create(self.lun, multipathing=True)
        self.hostWithMultiplePaths.addSR(self.sr, default=True)
        
        xenrt.TEC().logverbose("Successfully created LVMoHBA SR")
        
        if self.scsiid == self.sr_scsiid:
            raise xenrt.XRTFailure("Expecting different SCSI ID for SR.")

        self.guest = self.hostWithMultiplePaths.createGenericLinuxGuest()
        dev = self.guest.createDisk(sizebytes=5*xenrt.GIGA, sruuid=self.sr.uuid, returnDevice=True) # 5GB
        time.sleep(5)
        
        # Launch a periodic read/write script using the new disk
        self.guest.execguest("%s/remote/readwrite.py /dev/%s > /tmp/rw.log "
                             "2>&1 < /dev/null &" %
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), dev))

        time.sleep(20)    
        self.checkGuest()
        
        xenrt.TEC().logverbose("Successfully created and started generic linux guest.")

    def postRun(self):
            self.sr.remove() # destroys the FC SR and release the associated FC LUN.
            try:
                self.hostWithMultiplePaths.enableAllFCPorts() # Enable all FC ports.
            except:
                xenrt.TEC().warning("Unable to bring up one or more FC ports of the switch")

    def checkGuest(self):
        # Check the periodic read/write script is still running on the VM
        rc = self.guest.execguest("pidof python",retval="code")
        if rc > 0:
            # Get the log
            self.guest.execguest("cat /tmp/rw.log || true")
            raise xenrt.XRTFailure("Periodic read/write script failed")

        try:
            first = int(float(self.guest.execguest("tail -n 1 /tmp/rw.log").strip()))
            xenrt.sleep(30)
            next = int(float(self.guest.execguest("tail -n 1 /tmp/rw.log").strip()))
            if next == first:
                raise xenrt.XRTFailure("Periodic read/write script has not "
                                       "completed a loop in 30 seconds")
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTError("Exception checking read/write script progress",
                                 data=str(e))

class _PathFailureAndRestore(_HardwareMultipath):
    """Test simulating FC path failure and restore."""
    FAILURE_PATH = 0
    def run(self, arglist=None):
        _HardwareMultipath.run(self, arglist=None)
        
        self.disableFCPort(self.FAILURE_PATH)
        self.checkGuest()

        self.enableFCPort(self.FAILURE_PATH)
        self.checkGuest()

class TC12150(_PathFailureAndRestore):
    """Test simulating FC primary path failure and restore."""
    FAILURE_PATH = 0

class TC12151(_PathFailureAndRestore):
    """Test simulating FC secondary path failure and restore."""
    FAILURE_PATH = 1

class TC12152(_HardwareMultipath):
    """Test looping over FC primary and secondary paths, failing and restoring."""
    
    NUM_LOOPS = 10
   
    def run(self, arglist=None):
        _HardwareMultipath.run(self, arglist=None)
        
        failPrimary = True
        for i in range(self.NUM_LOOPS):
            xenrt.TEC().logverbose("Starting loop iteration %u/%u" % (i+1, self.NUM_LOOPS))
            if failPrimary:
                self.disableFCPort(0)
            else:
                self.disableFCPort(1)

            self.checkGuest()

            if failPrimary:
                self.enableFCPort(0)
            else:
                self.enableFCPort(1)

            self.checkGuest()

            failPrimary = not failPrimary

class TC12153(_HardwareMultipath):
    """Test guest suspend, resume and destroy operations with each FC path in failure state."""
    def run(self, arglist=None):
        _HardwareMultipath.run(self, arglist=None)
        
        self.guest.suspend()
        self.guest.resume()
        self.checkGuest()

        self.disableFCPort(0)
        self.checkGuest()
        self.guest.suspend()
        self.guest.resume()
        self.checkGuest()
        
        self.enableFCPort(0)
        self.checkGuest()
        self.guest.suspend()
        self.guest.resume()
        self.checkGuest()
        
        self.disableFCPort(1)
        self.checkGuest()
        self.guest.suspend()
        self.guest.resume()
        self.checkGuest()
        
        self.enableFCPort(1)
        self.checkGuest()
        self.guest.suspend()
        self.guest.resume()
        self.checkGuest()

class TC12154(_HardwareMultipath):
    """Test SR operation with each FC path in failure state."""
    def checkThenDestroySR(self):
        self.sr.forget(release=False)
        self.sr.introduce()
        self.sr.check()
        self.sr.remove() # destroys it.
        self.sr = None
    
    def createSR(self):
        self.sr = xenrt.lib.xenserver.FCStorageRepository(self.hostWithMultiplePaths, "fc")
        self.sr.create(self.sr_scsiid, multipathing=True)
        self.hostWithMultiplePaths.addSR(self.sr, default=True)
    
    def run(self, arglist=None):
        _HardwareMultipath.run(self, arglist=None)

        self.sr.remove() # Removes all the existing VMs from previous test + the FC SR.
        
        self.disableFCPort(0)
        self.createSR()
        self.checkThenDestroySR()

        self.enableFCPort(0)
        self.createSR()
        self.checkThenDestroySR()
        
        self.disableFCPort(1)
        self.createSR()
        self.checkThenDestroySR()

        self.enableFCPort(1)
        self.createSR()
        self.checkThenDestroySR()

class _HASmokeTestWithPathDown(testcases.xenserver.tc.ha._HASmoketest, _HardwareMultipath):
    """HA smoke test with FC path down"""
    STATEFILE_SR = "lvmoiscsi"
    NUMHOSTS = 2
    FAILURE_PATH = 0
    ROOTDISK_MPATH_COUNT = 4
    DEFAULT_PATH_COUNT = 1
    
    def prepare(self, arglist=None):
        for h in self.getDefaultPool().getHosts():
            if h.lookup(["FC", "CMD_HBA0_ENABLE"], None) != None and h.lookup(["FC", "CMD_HBA1_ENABLE"], None) != None:
                self.hostWithMultiplePaths = h
                self.scsiid = string.split(h.lookup("OPTION_CARBON_DISKS", None), "scsi-")[1]
                break
            
        _HardwareMultipath.disableFCPort(self, self.FAILURE_PATH)

        testcases.xenserver.tc.ha._HASmoketest.prepare(self)

    def postRun(self):
        testcases.xenserver.tc.ha._HASmoketest.postRun(self)
        
        xenrt.TEC().logverbose("Enabling FC Port %u" % self.FAILURE_PATH)
        _HardwareMultipath.enableFCPort(self, self.FAILURE_PATH)
        xenrt.TEC().logverbose("Successfully enabled FC Port %u" % self.FAILURE_PATH)


class TC12155(_HASmokeTestWithPathDown):
    """HA smoke test with primary FC path down."""
    FAILURE_PATH = 0

class TC12156(_HASmokeTestWithPathDown):
    """HA smoke test with secondary FC path down."""
    FAILURE_PATH = 1

class TC21455(xenrt.TestCase):
    """Test to verify multipathd restarts and reload after segmentation fault HFX-989 and HFX-988"""
    
    def prepare(self,arglist=None):
        
        self.host=self.getDefaultHost()
        self.host.enableMultipathing()

    def run(self,arglist=None):
       
         # Killing existing Multipathd daemon
        commandOutput = self.host.execdom0("killall multipathd; exit 0").strip()
        if "multipathd: no process killed" in commandOutput:
            xenrt.TEC().logverbose("No previously running multipathd process to terminate.")
        else: 
            pid = self.host.execdom0("pidof multipathd || true").strip()
            if pid == "":
                xenrt.TEC().logverbose("The previously running multipathd process is terminated.")
            else:
                raise xenrt.XRTFailure("The previously running multipathd deamon is still running.")

        #mutlipathd should reload in <<2min+2s
        timeout=122
        deadline=xenrt.timenow()+timeout
        while(xenrt.timenow()<=deadline):
            pid = self.host.execdom0("pidof multipathd || true").strip()
            if pid :
                xenrt.TEC().logverbose("Multipathd restarted with process id %s" % (pid))
                break
        if(xenrt.timenow() > deadline):
            raise xenrt.XRTFailure("Mutlipathd did not restart with in 2m+2s")
        
        #creating FC SR  
        fcLun = xenrt.HBALun([self.host])
        scsiid = fcLun.getID()
        fcSR = xenrt.lib.xenserver.FCStorageRepository(self.host, "fc")
        fcSR.create(fcLun, multipathing=True)
        activeMPathBeforeFailover = self.host.getMultipathInfo(onlyActive=True)
        self.host.disableFCPort(0)
        xenrt.sleep(100)
        activeMPathAfterFailover = self.host.getMultipathInfo(onlyActive=True)
        if (len(activeMPathAfterFailover[scsiid])!= len(activeMPathBeforeFailover[scsiid])-1):
            raise xenrt.XRTFailure("expected %d paths active" % (len(activeMPathBeforeFailover[scsiid])-1))
        self.host.enableFCPort(0)
        xenrt.sleep(100)
        activeMPathRestored = self.host.getMultipathInfo(onlyActive=True)
        if (len(activeMPathRestored[scsiid])!= len(activeMPathBeforeFailover[scsiid])):
            raise xenrt.XRTFailure("original path did not get restored")

class TC18155(xenrt.TestCase):
    """Test that xapi attaches the MGT volume to the multipath node rather than the raw disk node after a reboot (HFX-447)"""
    
    def run(self, arglist=None):
        TIMEOUT = 900 # 15 minutes
        host = self.getHost("RESOURCE_HOST_0")
        fcsruuid = host.parseListForUUID("sr-list", "name-label", "fcsr")

        # Wait until the FC SR is plugged in.
        deadline = xenrt.timenow() + TIMEOUT
        while 1:
            pbds = host.minimalList("pbd-list",args="sr-uuid=%s" % fcsruuid)
            if len(pbds) >= 1: # expecting a single pbd in this test case anyway.
                if host.genParamGet("pbd", pbds[0], "currently-attached") == "true":
                    break

            if xenrt.timenow() > deadline:
                raise xenrt.XRTFailure("Timed out waiting for FC SR to be plugged in. Current timeout %d seconds." % TIMEOUT)
            xenrt.sleep(15)

        diskNode = host.execdom0("dmsetup table | grep %s-MGT | awk '{ print $5 }'" % (fcsruuid.replace("-","--"))).strip()
        if not diskNode:
            host.execdom0("dmsetup table")
            raise xenrt.XRTFailure("MGT volume for FC SR [UUID %s] is not found." % fcsruuid)

        mpathdevice = host.execdom0("""awk '$2 == "device-mapper" { print $1 }' /proc/devices""").strip()

        if diskNode.split(":")[0] != mpathdevice:
            host.execdom0("dmsetup table")
            raise xenrt.XRTFailure("Disk node on MGT volume is not the multipath node, expected %s:*" % mpathdevice)

class TC18156(xenrt.TestCase):
    """CA-89356: ISCSI Software initiator multipathing for Dell EqualLogic targets"""
    
    # this was released for a Sanibel hotfix (HFX-455) 
    
    def prepare(self, arglist=None):
        self.host = self.getHost("RESOURCE_HOST_0")
        self.host.enableMultipathing()
        networks = self.host.minimalList("pif-list","network-uuid","management=false IP-configuration-mode=DHCP")
        self.host.execdom0("sed -i '/#devices/d' /etc/multipath.conf")
        eqlmpconf = "\\tdevice {\\n"
        eqlmpconf += "\\t\\tvendor \"EQLOGIC\"\\n"
        eqlmpconf += "\\t\\tproduct \"100E-00\"\\n"
        eqlmpconf += "\\t\\tpath_grouping_policy multibus\\n"
        
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            eqlmpconf += "\\t\\tgetuid_callout \"" + self.host.scsiIdPath() + " -g -u --devices /dev/%n\"\\n"
        else:
            eqlmpconf += "\\t\\tgetuid_callout \"" + self.host.scsiIdPath() + " -g -u -s /block/%n\"\\n"
        
        eqlmpconf += "\\t\\tpath_checker readsector0\\n"
        eqlmpconf += "\\t\\tfailback immediate\\n"
        eqlmpconf += "\\t\\tpath_selector \"round-robin 0\"\\n"
        eqlmpconf += "\\t\\trr_weight priorities\\n"
        eqlmpconf += "\\t}\\n"
        self.host.execdom0("sed -i 's#devices {#devices {\\n%s#' /etc/multipath.conf" % eqlmpconf)
        i = 0
        for n in networks:
            bridge = self.host.genParamGet("network", n, "bridge")
            self.host.execdom0("iscsiadm -m iface --op new -I c_iface%d" % i)
            ret = self.host.execdom0("iscsiadm -m iface --op update -I c_iface%d -n iface.net_ifacename -v %s" % (i, bridge), retval="code")
            if ret != 19:
                raise xenrt.XRTError("Setting up iscsi interface failed with %d, expected 19" % ret)
            i += 1
        self.host.reboot()
        self.eql = xenrt.EQLTarget(minsize=40, maxsize=1000000)
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host, "cvsmeqlsr")
        self.sr.create(self.eql,protocol="iscsi",physical_size=None)
        self.guest = self.host.createGenericLinuxGuest(sr = self.sr.uuid)
        self.guestDevice = self.guest.createDisk(sizebytes=1*xenrt.GIGA, sruuid=self.sr.uuid, returnDevice=True)

    def checkGuestDisk(self):
        self.guest.execguest("mkfs.ext3 /dev/%s" % self.guestDevice)

    def waitForMultipathCount(self,expected,timeout=300):
        vdi = self.host.minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s device=%s" % (self.guest.uuid, self.guestDevice))[0]
        scsi = self.host.genParamGet("vdi",vdi,"sm-config","SCSIid")
        pbd = self.host.minimalList("pbd-list", "uuid", "sr-uuid=%s" % self.sr.uuid)[0]

        now = xenrt.util.timenow()
        deadline = now + timeout
        while True:
            counts = self.host.getMultipathCounts(pbd,scsi)
            if counts == expected:
                break
            now = xenrt.util.timenow()
            if now > deadline:
                raise xenrt.XRTFailure("Timed out waiting for correct multipath counts - expected %d/%d, got %d/%d"  % (expected[0], expected[1], counts[0], counts[1]))
            time.sleep(15)
        

    def run(self, arglist=None):
        macs = self.host.minimalList("pif-list","MAC","management=false IP-configuration-mode=DHCP")
        self.checkGuestDisk()
        # Now fail a path
        self.host.disableNetPort(macs[0])
        self.checkGuestDisk()
        self.waitForMultipathCount([1,2])
        self.checkGuestDisk()

        # And restore it
        self.host.enableNetPort(macs[0])
        self.waitForMultipathCount([2,2])
        self.checkGuestDisk()

        # Now fail the ogrep -ther path
        self.host.disableNetPort(macs[1])
        self.checkGuestDisk()
        self.waitForMultipathCount([1,2])
        self.checkGuestDisk()
        
        # And restore it
        self.host.enableNetPort(macs[1])
        
        self.waitForMultipathCount([2,2])
        self.checkGuestDisk()
        
    def postRun(self):
        self.guest.shutdown()
        self.guest.uninstall()
        self.sr.destroy()
        self.eql.release()

class TCIQNWildcard(xenrt.TestCase):
    """TC-18159: Regression test for CA-63999 (multipathing with IQN wildcard)"""

    def countPaths(self, scsiId):
        # There should be 2 paths to a lun
        mp = self.host.getMultipathInfo()
        
        if len(mp[scsiId]) != 2:
            raise xenrt.XRTFailure("Should be 2 paths available.")

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.host.enableMultipathing()
        self.guest = self.host.createGenericLinuxGuest()
        
        # get bridge for first PIF which isn't management
        networks = self.host.minimalList("pif-list", "network-uuid", "management=false IP-configuration-mode=DHCP")
        bridge = self.host.genParamGet("network", networks[0], "bridge")
        
        # need multiple VIFs for multipathing
        self.guest.createVIF("eth1", bridge, mac=None, plug=True)
        xenrt.sleep(10)
        self.guest.execguest("echo 'auto eth1' >> "
                             "/etc/network/interfaces")
        self.guest.execguest("echo 'iface eth1 inet dhcp' >> "
                             "/etc/network/interfaces")
        self.guest.execguest("echo 'post-up route del -net default "
                             "dev eth1' >> /etc/network/interfaces")
        self.guest.execguest("ifup eth1")
        xenrt.sleep(60)
        self.iqn = self.guest.installLinuxISCSITarget()
        self.guest.createISCSITargetLun(0, 1024)
        
    def run(self, arglist=None):

        cli = self.host.getCLIInstance()
        ip0 = self.guest.getVIFs()['eth0'][1]
        ip1 = self.guest.getVIFs()['eth1'][1]
        
        # temp hack to start iscsi daemon. Fixed on Tampa and later.
        if not isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            try:
                cli.execute("sr-probe", "type=lvmoiscsi device-config:multihomed=true device-config:target=%s" % ip0)
            except:
                pass
        
        log("Create ISCSI SR via single target IP search")
        # get SCSI id for LUN
        try:
            xml = cli.execute("sr-probe", "type=lvmoiscsi device-config:multihomed=true device-config:target=%s device-config:targetIQN=*" % ip0)
        except Exception, e:
            xml = str(e.data)
                    
        scsiId = re.search(r"<SCSIid>(.*)</SCSIid>", xml, re.MULTILINE|re.DOTALL).group(1).strip()

        # create SR using IQN wildcard
        sr = cli.execute("sr-create", "name-label=mySR type=lvmoiscsi device-config:targetIQN=* device-config:SCSIid=%s device-config:target=%s" % (scsiId, ip0)).strip()
        
        # check paths
        self.countPaths(scsiId)

        self.host.forgetSR(sr)
        
        log("Create ISCSI SR via multiple target IP search")
        # check port :3260 is not appended
        try:
            xml = cli.execute("sr-probe", "type=lvmoiscsi device-config:target=%s,%s device-config:port=3260" % (ip0, ip1))
        except Exception, e:
            xml = str(e.data)
        
        badString = ip0 + "," + ip1 + ":3260"
        if re.search(badString, xml):
            raise xenrt.XRTFailure("During sr-probe, extra portNumber is appended to IPAddress string")
        
        # get SCSIid for LUN
        try:
            xml = cli.execute("sr-probe", "type=lvmoiscsi device-config:multihomed=true "
                              "device-config:target=%s,%s device-config:port=3260 device-config:targetIQN=*" % (ip0, ip1))
        except Exception, e:
            xml = str(e.data)
        
        scsiId = re.search(r"<SCSIid>(.*)</SCSIid>", xml, re.MULTILINE|re.DOTALL).group(1).strip()

        # create SR using specified IQN
        sr = cli.execute("sr-create", "name-label=mySR type=lvmoiscsi device-config:targetIQN=%s "
                         "device-config:SCSIid=%s device-config:target=%s,%s device-config:port=3260" % (self.iqn, scsiId, ip0, ip1)).strip()
        # check paths
        self.countPaths(scsiId)
        
        self.host.forgetSR(sr)
        
        # create SR using IQN wildcard
        sr = cli.execute("sr-create", "name-label=mySR type=lvmoiscsi device-config:targetIQN=* "
                         "device-config:SCSIid=%s device-config:target=%s,%s device-config:port=3260" % (scsiId, ip0, ip1)).strip()
        # check paths
        self.countPaths(scsiId)
        
        self.host.forgetSR(sr)
         

class TC18782(xenrt.TestCase):
    """Verify memory corruption in multipathd when it gets stuck during switch port failure (HFX-630)"""

    NUM_LOOPS = 10
    DELAY = 40

    def prepare(self, arglist=None):

        # Parse the arguments, if provided in sequence file.
        for arg in arglist:
            if arg.startswith('iterations'):
                self.NUM_LOOPS = int(arg.split('=')[1])
            if arg.startswith('delay'):
                self.DELAY = int(arg.split('=')[1])

        # Get the host.
        self.host = self.getHost("RESOURCE_HOST_0")

        # Get the multipath debuginfo rpm. The version of the rpm must match the version of device-mapper-multipath rpm.
        commandInput = "rpm -qa device-mapper-multipath | sed 's/device-mapper-multipath/device-mapper-multipath-debuginfo/'"
        multipathDebuginfoRpmFileName = self.host.execdom0(commandInput).strip()

        if multipathDebuginfoRpmFileName: # e.g. device-mapper-multipath-debuginfo-0.4.7-46.xs1033
        
            if not isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
                multipathDebuginfoRpmFilePath = xenrt.TEC().getFile("binary-packages/RPMS/domain0/RPMS/i386/%s.i386.rpm" %
                                                                                                multipathDebuginfoRpmFileName)
            else:
                multipathDebuginfoRpmFilePath = xenrt.TEC().getFile("binary-packages/RPMS/domain0/RPMS/x86_64/valgrind-3.*.rpm")

            if not multipathDebuginfoRpmFilePath:
                xenrt.TEC().logverbose("Device-mapper-multipath-debuginfo file path does not exist. "
                                        "A different version of device-mapper-multipath-debuginfo may exist. "
                                        "Skipping installation of device-mapper-multipath-debuginfo RPM.")
            else:
                xenrt.TEC().logverbose("Trying to install device-mapper-multipath-debuginfo RPM.")
                try:
                    xenrt.checkFileExists(multipathDebuginfoRpmFilePath)
                except:
                    raise xenrt.XRTFailure("Device-mapper-multipath-debuginfo file is not found: %s" %
                                                                                    multipathDebuginfoRpmFilePath)

                # Copy RPM from the controller to host in test
                hostPath = "/tmp/%s.i386.rpm" % (multipathDebuginfoRpmFileName)
                sh = self.host.sftpClient()
                try:
                    sh.copyTo(multipathDebuginfoRpmFilePath, hostPath)
                finally:
                    sh.close()

                try:
                    self.host.execdom0("rpm -i /tmp/%s.i386.rpm" % multipathDebuginfoRpmFileName)
                except:
                    xenrt.TEC().logverbose("Unable to install the device-mapper-multipath-debuginfo rpm")
        else:
            raise xenrt.XRTFailure("Device-mapper-multipath rpm that is part of Xenserver base installation is not installed.")

    def run(self, arglist=None):

        # Install Memcheck, a memory error detector using Valgrind
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            pass # Nothing to do as the package gdb (gdb-7.6.1-51.el7.x86_64) already installed and latest version.
        elif isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            # Valgrind v3.9.0 for Creedence.
            script = """#!/usr/bin/expect
    set timeout 180
    spawn yum --disablerepo=citrix --enablerepo=base install gdb
    expect -exact "Is this ok"
    sleep 5
    send -- "y\r"
    expect -exact "Complete"
    expect eof
    """
            self.host.execdom0("echo '%s' > script.sh; exit 0" % script)
            self.host.execdom0("chmod a+x script.sh; exit 0")
            self.host.execdom0("/root/script.sh")
        else: # Any other hosts.
            self.host.execdom0("yum --disablerepo=citrix --enablerepo=base install -y gdb valgrind") # Valgrind v3.5.0

        # Clean existing multipathd deamon, if any
        commandOutput = self.host.execdom0("killall multipathd; exit 0").strip()
        if "multipathd: no process killed" in commandOutput:
            xenrt.TEC().logverbose("No previously running multipathd process to terminate.")
        else: 
            pid = self.host.execdom0("pidof multipathd || true").strip()
            if pid == "":
                xenrt.TEC().logverbose("The previously running multipathd process is terminated.")
            else:
                raise xenrt.XRTFailure("The previously running multipathd deamon is still running.")

        # Start multipathd with valgrind
        args = []
        args.append("--tool=memcheck -v")
        args.append("--log-file=/root/multipathdvalgrindlog.txt")
        args.append("--track-fds=yes")
        args.append("--read-var-info=yes")
        args.append("--track-origins=yes")
        args.append("--num-callers=10")

        multipathdStartCommand = "/sbin/multipathd -v3 -x -e -d"
        multipathdLogOutput = "/root/multipathdlog.txt"
        self.host.execdom0("valgrind " + string.join(args) + " " + multipathdStartCommand + " > " + multipathdLogOutput + " &")

        # Check whether the newly initiated multipathd deamon with valgrind is running.
        pid = self.host.execdom0("pidof valgrind || true").strip()
        if pid == "":
            raise xenrt.XRTFailure("valgrind: multipathd deamon is not running to proceed with the test.")
        else:
            xenrt.TEC().logverbose("valgrind: multipathd deamon is running ...")

        # Down and up available paths in a loop with a DELAY (in secs) for a few iterations.
        flag = True
        for i in range(self.NUM_LOOPS):
            xenrt.TEC().logverbose("Starting loop iteration %u/%u" % (i+1, self.NUM_LOOPS))

            if (flag):
                xenrt.TEC().logverbose("Trying to bring down all available FC paths.")
                self.host.disableAllFCPorts()
            else:
                xenrt.TEC().logverbose("Trying to bring up all available FC paths.")
                self.host.enableAllFCPorts()

            time.sleep(self.DELAY) # Waiting for a DELAY.
            flag = not flag # Disable ports alternatively.

        time.sleep(self.DELAY * 2) # Waiting for more time to procceed.

        # Check that there is no "Invalid" string in /root/multipathdvalgrindlog.txt
        try:
            multipathdLogFile = self.host.execdom0("cat multipathdvalgrindlog.txt; exit 0")
        except:
            raise xenrt.XRTFailure("Couldn't open /root/multipathdvalgrindlog.txt for error detection.")

        if re.search(r"Invalid", multipathdLogFile):
            raise xenrt.XRTFailure("Valgrind Memcheck detected memory corruption in multipathd during path failures.")
        else:
            xenrt.TEC().logverbose("No memory corruption detected using Valgrind Memcheck tool.")

    def postRun(self):
        # Clean running multipathd: valgrind demaons
        commandOutput = self.host.execdom0("killall valgrind; exit 0").strip()
        if "valgrind: no process killed" in commandOutput:
            xenrt.TEC().logverbose("No running valgrind: multipathd process to terminate.")
        else: 
            pid = self.host.execdom0("pidof valgrind || true").strip()
            if pid == "":
                xenrt.TEC().logverbose("The running valgrind: multipathd process is terminated.")
                # Delete the Valgrind log file.
                self.host.execdom0("rm -f /root/multipathdvalgrindlog.txt")
                xenrt.TEC().logverbose("The valgrind: multipathdvalgrindlog file is not deleted yet.")
            else:
                raise xenrt.XRTFailure("valgrind: multipathd deamon is still running.")

class TC18783(TC8141): # Loop of fail-recover on alternate paths
    """Verify the race condition in DM Multipath when a path disappears while it is added (HFX-631)"""

    USEVLANS = False
    DEFAULT_LOOPS = 10
    MPP_RDAC = True

    def run(self, arglist=None):

        # Add paths and take them down again quickly in a loop for some iterations
        TC8141.run(self, arglist) # Run all the contructs in Base class.

        # iscsiadm -m node --login && iscsiadm -m node --logout
        data = self.host.execdom0("iscsiadm -m session")
        if not "No active sessions" in data:
            xenrt.TEC().logverbose("Found active iSCSI sessions. Try to logout sessions.")
            self.host.execdom0("iscsiadm -m node --logout")
        else:
            xenrt.TEC().logverbose("There are no active iSCSI sessions as required.")

        for i in range(self.DEFAULT_LOOPS * 2):
            xenrt.TEC().logverbose("Starting iteration %u/%u" % (i+1,self.DEFAULT_LOOPS * 2))
            self.host.execdom0("iscsiadm -m node --login && iscsiadm -m node --logout")

        # Check that multipathd -k"show top" still prints the topology
        mpdevs = self.host.getMultipathInfo(onlyActive=False,useLL=False)
        
        if not mpdevs.has_key(self.scsiID):
            raise xenrt.XRTFailure("No multipath info found for our SCSI ID",
                                   "ID %s, info %s" %
                                   (self.scsiID, str(mpdevs)))

class TC18785(xenrt.TestCase):
    """Verify the integration of storage backend driver to support Borahamwood features (HFX-578)"""

    def run(self, arglist=None):

        # Get the host.
        self.host = self.getHost("RESOURCE_HOST_0")

        # Check whether the modified code to support Borahamwood features is in place.
        codeLine = self.host.execdom0("cat /opt/xensource/sm/mpathcount.py | grep rawhba; exit 0")
        if (codeLine):
            xenrt.TEC().logverbose("Integration of storage backend driver to support Borahamwood features is in place.")
        else:
            raise xenrt.XRTFailure("Storage backend driver to support Borahamwood features is not found.")

class TC18786(xenrt.TestCase):
    """Verify multipath.conf invalid keyword errors are not thrown when using multipath utility (HFX-679)"""

    def run(self, arglist=None):

        # Get the host.
        self.host = self.getHost("RESOURCE_HOST_0")

        # Check whether multipath command has any invalid keyword errors.
        commandOutput = self.host.execdom0("multipath -ll; exit 0")
        if "DM multipath kernel driver not loaded" in commandOutput:
            raise xenrt.XRTFailure("DM multipath kernel driver not loaded on the current configured host.")
        else:
            # Search for "multipath.conf line 46, invalid keyword:" string in output.
            if re.search(r".*?multipath.conf.*?invalid keyword:", commandOutput):
                raise xenrt.XRTFailure("multipath.conf invalid keyword errors are found while using multipath command.")
            else:
                xenrt.TEC().logverbose("No multipath.conf invalid keyword errors are found while using multipath command.")

class TC18787(xenrt.TestCase):
    """Verify the iSCSI multipath problem during host activity (HFX-680)"""
    # Duplicate TC-18821  is closed. [Verify recovery when primary path is down and host rebooted]

    def prepare(self, arglist=None):
        # Get 2 hosts
        self.host = self.getHost("RESOURCE_HOST_0")
        self.host.enableMultipathing()
        self.targetHost = self.getHost("RESOURCE_HOST_1")
        self.targetHost.enableMultipathing()

        # Configure the host networking
        netconfig = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>   
    <MANAGEMENT/>
  </PHYSICAL>    
  <PHYSICAL network="NSEC">
    <NIC/>
    <STORAGE/>
  </PHYSICAL>
</NETWORK>"""
        self.paths = 2

        self.host.createNetworkTopology(netconfig)
        self.targetHost.createNetworkTopology(netconfig)
        
        # Create Target
        self.target = self.targetHost.createGenericLinuxGuest()
        secnetworks = self.targetHost.minimalList("network-list")
        eIndex = 1
        for n in secnetworks:
            bridge = self.targetHost.genParamGet("network", n, "bridge")
            try:
                if bridge == self.targetHost.getPrimaryBridge() or \
                    self.targetHost.genParamGet("network", n, "other-config",
                                          "is_guest_installer_network") == "true":
                    continue
            except:
                    pass
            # See if the PIF associated with this network has an IP on
            pif = self.targetHost.minimalList("pif-list", args="network-uuid=%s" % (n))[0]
            if self.targetHost.genParamGet("pif", pif, "IP-configuration-mode") == "None":
                continue
            self.target.createVIF(eth="eth%u" % (eIndex), bridge=bridge, 
                                      plug=True)
            time.sleep(5)
            self.target.execguest("echo 'auto eth%u' >> "
                                      "/etc/network/interfaces" % (eIndex))
            self.target.execguest("echo 'iface eth%u inet dhcp' >> "
                                      "/etc/network/interfaces" % (eIndex))
            self.target.execguest("echo 'post-up route del -net default dev "
                                      "eth%u' >> /etc/network/interfaces" % (eIndex))
            self.target.execguest("ifup eth%u" % (eIndex))
            eIndex += 1

        self.getLogsFrom(self.target)

        # Configure large iSCSI target on second host
        dev = self.target.createDisk(sizebytes=10737418240, returnDevice=True)
        time.sleep(5)
        self.target.execguest("mkfs.ext3 /dev/%s" % dev)
        self.target.execguest("mkdir -p /iscsi")
        self.target.execguest("mount /dev/%s /iscsi" % dev)
        self.initiator = "xenrt-test"
        self.targetiqn = self.target.installLinuxISCSITarget()
        self.target.createISCSITargetLun(0, 8096, dir="/iscsi/")
        self.targetip = self.target.getIP()
        self.lunid = 0
        
        
        # Primary path
        self.priIP = self.target.getIP()
        
        # Secondary path
        self.secIP = self.target.getLinuxIFConfigData()["eth1"]["IP"]
        
        # Creare sr on the target using the 2 paths
        # get SCSI id for LUN
        cli = self.host.getCLIInstance()
        try:
            xml = cli.execute("sr-probe", "type=lvmoiscsi device-config:multihomed=true device-config:target=%s,%s device-config:targetIQN=*" % (self.priIP, self.secIP))
        except Exception, e:
            xml = str(e.data)
                    
        self.scsiID = re.search(r"<SCSIid>(.*)</SCSIid>", xml, re.MULTILINE|re.DOTALL).group(1).strip()
        
        # Creare sr on the target using the 2 paths
        self.sr = cli.execute("sr-create", "name-label=mySR type=lvmoiscsi device-config:targetIQN=* device-config:SCSIid=%s device-config:target=%s,%s" % (self.scsiID, self.priIP, self.secIP))
        self.sr = self.sr.strip('\n')
        
        self.pbd = self.host.parseListForUUID("pbd-list",
                                    "sr-uuid",
                                    self.sr,
                                    "host-uuid=%s" % (self.host.getMyHostUUID()))

        time.sleep(150)
        
        # now check paths
        mp = self.host.getMultipathInfo(onlyActive=True)
        if len(mp[self.scsiID]) != self.paths:
            raise xenrt.XRTError("Only %u/%u paths active before test started" %
                                     (len(mp[self.scsiID]),self.paths))
        
    def run(self, arglist=None):
        cli = self.host.getCLIInstance()
        # Unplug SR 
        cli.execute("pbd-unplug", "uuid=%s" % (self.pbd))
        
        # Bring down the primary path
        # Assuming eth0
        self.failPath = 'eth0'
        
        self.target.execguest("iptables -I INPUT -i %s -p tcp -m tcp "
                                  "--dport 3260 -j DROP" % (self.failPath))
        self.target.execguest("iptables -I OUTPUT -o %s -p tcp -m tcp "
                                  "--sport 3260 -j DROP" % (self.failPath))
                                  
        # Wait 
        time.sleep(50)
        
        # Plug back the SR
        cli.execute("pbd-plug", "uuid=%s" % (self.pbd))
        
        # Verify the SR is attached
        if self.host.genParamGet("pbd", self.pbd, "currently-attached") == "true":
            xenrt.TEC().logverbose("SR is reattached with %u/%u paths active" %
                                          ((self.paths - 1),self.paths))
        else:
            raise xenrt.XRTFailure("SR is disconnected even if %u/%u paths is active" %
                                          ((self.paths - 1),self.paths))
         
        # Recover the primary path
        self.target.execguest("iptables -D INPUT -i %s -p tcp -m tcp "
                                  "--dport 3260 -j DROP" % (self.failPath))
        self.target.execguest("iptables -D OUTPUT -o %s -p tcp -m tcp "
                                  "--sport 3260 -j DROP" % (self.failPath))
        
        time.sleep(10)
        
        # Repair the broken SR
        cli.execute("pbd-plug", "uuid=%s" % (self.pbd))
        
        # Verify the SR is attached
        if self.host.genParamGet("pbd", self.pbd, "currently-attached") == "true":
            xenrt.TEC().logverbose("SR is reattached after primary path recovery")
        else:
            raise xenrt.XRTFailure("SR not reattached after primary path recovery")
        
        # Verify path counts
        mp = self.host.getMultipathInfo(onlyActive=True)
        if len(mp[self.scsiID]) != self.paths:
            #NOTE: To be fixed in CA-73867
            xenrt.TEC().warning("Only %u/%u paths active after SR is repaired" %
                                     (len(mp[self.scsiID]),self.paths))
        
        # Unplug SR 
        cli.execute("pbd-unplug", "uuid=%s" % (self.pbd))
        
        # Bring down the alternate path
        # Assuming eth1
        self.failPath = 'eth1'
        
        self.target.execguest("iptables -I INPUT -i %s -p tcp -m tcp "
                                  "--dport 3260 -j DROP" % (self.failPath))
        self.target.execguest("iptables -I OUTPUT -o %s -p tcp -m tcp "
                                  "--sport 3260 -j DROP" % (self.failPath))
                                  
        # Wait 
        time.sleep(50)
        
        # Plug back the SR
        cli.execute("pbd-plug", "uuid=%s" % (self.pbd))
        
        # Verify the SR is attached
        if self.host.genParamGet("pbd", self.pbd, "currently-attached") == "true":
            xenrt.TEC().logverbose("SR is reattached with %u/%u paths active" %
                                          ((self.paths - 1),self.paths))
        else:
            raise xenrt.XRTFailure("SR is disconnected even if %u/%u paths is active" %
                                          ((self.paths - 1),self.paths))
        
        # Recover the secondary path
        self.target.execguest("iptables -D INPUT -i %s -p tcp -m tcp "
                                  "--dport 3260 -j DROP" % (self.failPath))
        self.target.execguest("iptables -D OUTPUT -o %s -p tcp -m tcp "
                                  "--sport 3260 -j DROP" % (self.failPath))
        
        time.sleep(10)
        
        # Repair the broken SR
        cli.execute("pbd-plug", "uuid=%s" % (self.pbd))
        
        # Verify the SR is attached
        if self.host.genParamGet("pbd", self.pbd, "currently-attached") == "true":
            xenrt.TEC().logverbose("SR is reattached after primary path recovery")
        else:
            raise xenrt.XRTFailure("SR not reattached after primary path recovery")
        
        # Verify path counts
        mp = self.host.getMultipathInfo(onlyActive=True)
        if len(mp[self.scsiID]) != self.paths:
            #NOTE: To be fixed in CA-73867
            xenrt.TEC().warning("Only %u/%u paths active after SR is repaired" %
                                     (len(mp[self.scsiID]),self.paths))

class TCValidatePathCount(_TC8159):
    """Validate active/total paths of FC multipath SR after dropping paths"""
    PATHS = 2 # 2 paths
    MORE_PATHS_OK = True
    
    def createSR(self, host):
        lun = xenrt.HBALun([host])
        self.scsiid = lun.getID()
        sr = xenrt.lib.xenserver.FCStorageRepository(host, "fc")
        sr.create(lun,multipathing=True)
        return sr
        
    def run(self, arglist=None):
        _TC8159.run(self, arglist)
        host = self.getDefaultHost()
        
        totalPaths = len(host.getMultipathInfo()[self.scsiid])
        activePaths = len(host.getMultipathInfo(onlyActive=True)[self.scsiid])
        expectedPaths = [activePaths-2, totalPaths] # -2 because, the number of paths depends on the physical configuration.
        
        step("Drop one path by disabling port")
        host.disableFCPort(1)
        xenrt.sleep(60)
        
        step("Verify active and  total paths")
        pbd = host.parseListForUUID("pbd-list",
                                    "sr-uuid",
                                    self.sr.uuid,
                                    "host-uuid=%s" % (host.getMyHostUUID()))
        actualPaths = host.getMultipathCounts(pbd, self.scsiid)
        if expectedPaths != actualPaths:
            raise xenrt.XRTFailure("Multipaths not as expected: Expected:"
                                    "%d of %d paths active, Actual; %d of %d paths active" %
                                    (expectedPaths[0], expectedPaths[1], actualPaths[0], actualPaths[1]))
        else:
            xenrt.TEC().logverbose("Multipaths as expected: %d of %d active" % (actualPaths[0], actualPaths[1]))
            
    def postRun(self):
        self.getDefaultHost().enableFCPort(1)
        _TC8159.postRun(self)

class TCVerifyMultipathSetup(_TC8159):
    """Multipathing setup and SR creation using FCOE (lvmofcoe) SR"""
    PATHS = 2 # 2 paths
    MORE_PATHS_OK = True
    
    def createSR(self, host):
        self.lun = xenrt.HBALun([host])
        self.scsiid = self.lun.getID()
        sr = xenrt.lib.xenserver.FCOEStorageRepository(host, "fcoe")
        sr.create(self.lun,multipathing=True)
        return sr
        
class TCValidateFCOEMultipathPathCount(TCVerifyMultipathSetup):
    """Validate active/total paths of FCOE multipath SR after dropping paths"""
    PATHS = 2 # 2 paths
    MORE_PATHS_OK = True
    
    
    def disableEthPort(self, pathindex):
        
        xenrt.TEC().logverbose("Failing the path %d" % pathindex)
        
        mac = self.host.getNICMACAddress(pathindex)
        self.host.disableNetPort(mac)

    def enableEthPort(self, pathindex):
              
        xenrt.TEC().logverbose("Recovering the the path %d" % pathindex)
        
        mac = self.host.getNICMACAddress(pathindex)
        self.host.enableNetPort(mac)
        
    def run(self, arglist=None):
        _TC8159.run(self, arglist)
        self.host = self.getDefaultHost()
                
                
        totalPaths = len(self.host.getMultipathInfo()[self.scsiid])
        activePaths = len(self.host.getMultipathInfo(onlyActive=True)[self.scsiid])
        expectedPaths = [activePaths-4, totalPaths] # -4 because, the number of paths depends on the physical configuration.
        
        
        step("Drop one path by disabling port")
        self.disableEthPort(1)
        xenrt.sleep(60)
        
        step("Verify active and  total paths")
        pbd = self.host.parseListForUUID("pbd-list",
                                        "sr-uuid",
                                        self.sr.uuid,
                                        "host-uuid=%s" % (self.host.getMyHostUUID()))
        actualPaths = self.host.getMultipathCounts(pbd, self.scsiid)
        if expectedPaths != actualPaths:
            raise xenrt.XRTFailure("Multipaths not as expected: Expected:"
                                   "%d of %d paths active, Actual; %d of %d paths active" %
                                   (expectedPaths[0], expectedPaths[1], actualPaths[0], actualPaths[1]))
        else:
            xenrt.TEC().logverbose("Multipaths as expected: %d of %d active" % (actualPaths[0], actualPaths[1]))
            
        

    def postRun(self):
        self.enableEthPort(1)
        _TC8159.postRun(self)

class _PathFailOver(TCValidateFCOEMultipathPathCount):
    FAILURE_PATH = 1
    
    def checkGuestReadWrite(self):
        # Check the periodic read/write script is still running on the VM
        rc = self.guest.execguest("pidof python",retval="code")
        if rc > 0:
            # Get the log
            self.guest.execguest("cat /tmp/rw.log || true")
            raise xenrt.XRTFailure("Periodic read/write script failed")

        try:
            first = int(float(self.guest.execguest("tail -n 1 /tmp/rw.log").strip()))
            xenrt.sleep(30)
            next = int(float(self.guest.execguest("tail -n 1 /tmp/rw.log").strip()))
            if next == first:
                raise xenrt.XRTFailure("Periodic read/write script has not "
                                       "completed a loop in 30 seconds")
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTError("Exception checking read/write script progress",
                                 data=str(e))
        
    def run(self, arglist=None):
        _TC8159.run(self, arglist)
        self.host = self.getDefaultHost()
        dev = self.guest.createDisk(sizebytes=5*xenrt.GIGA, sruuid=self.sr.uuid, returnDevice=True) # 5GB
        xenrt.sleep(5)
        
        # Launch a periodic read/write script using the new disk
        self.guest.execguest("%s/remote/readwrite.py /dev/%s > /tmp/rw.log "
                             "2>&1 < /dev/null &" %
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), dev))

        xenrt.sleep(20)    
        self.checkGuestReadWrite()
                
        self.disableEthPort(self.FAILURE_PATH)
        self.checkGuestReadWrite()

        self.enableEthPort(self.FAILURE_PATH)
        self.checkGuestReadWrite()

class TCFCOESecondaryPathFailover(_PathFailOver):
    FAILURE_PATH = 1

class TCFCOEPrimaryPathFailover(_PathFailOver):
    FAILURE_PATH = 0
    
    def disablesysfs(self, portindex):
        self.host.execdom0("echo 0 > /sys/bus/fcoe/devices/ctlr_%u/enabled" % portindex)
        
    def enablesysfs(self, portindex):
        self.host.execdom0("echo 1 > /sys/bus/fcoe/devices/ctlr_%u/enabled" % portindex)
        
    def run(self,arglist=None):
        _TC8159.run(self, arglist)
        self.host = self.getDefaultHost()
        
        dev = self.guest.createDisk(sizebytes=5*xenrt.GIGA, sruuid=self.sr.uuid, returnDevice=True) # 5GB
                
        # Launch a periodic read/write script using the new disk
        self.guest.execguest("%s/remote/readwrite.py /dev/%s > /tmp/rw.log "
                             "2>&1 < /dev/null &" %
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), dev))

        xenrt.sleep(20)    
        self.checkGuestReadWrite()
                
        self.disablesysfs(self.FAILURE_PATH)
        xenrt.sleep(5)
        self.checkGuestReadWrite()

        self.enablesysfs(self.FAILURE_PATH)
        xenrt.sleep(5)
        self.checkGuestReadWrite()     


class TCCheckGuestOperations(_PathFailOver):


    def guestMethods(self):
        self.checkGuestReadWrite()
        self.guest.suspend()
        self.guest.resume()
        self.checkGuestReadWrite()

    def run(self,arglist=None):
        _TC8159.run(self, arglist)
        self.host = self.getDefaultHost()
        

        dev = self.guest.createDisk(sizebytes=5*xenrt.GIGA, sruuid=self.sr.uuid, returnDevice=True) # 5GB
        
        # Launch a periodic read/write script using the new disk
        self.guest.execguest("%s/remote/readwrite.py /dev/%s > /tmp/rw.log "
                             "2>&1 < /dev/null &" %
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), dev))

        xenrt.sleep(20)
            
        self.guest.suspend()
        self.guest.resume()
        self.checkGuestReadWrite()

        self.disableEthPort(1)
        self.guestMethods()
        
        self.enableEthPort(1)
        self.guestMethods()

        
class TCCheckSROperations(_PathFailOver):
    
    def checkThenDestroySR(self):
        self.sr.forget(release=False)
        self.sr.introduce()
        self.sr.check()
        self.sr.destroy()
        
    
    def run(self, arglist=None):
        _TC8159.run(self, arglist=None)
        self.host = self.getDefaultHost()
        
        self.guest.shutdown()
        self.guest.lifecycleOperation("vm-destroy", force=True)
        
        
        cli = self.host.getCLIInstance()
        vdis = self.host.minimalList("vdi-list", args="sr-uuid=%s" % self.sr.uuid)
        for vdi in vdis:
            cli.execute("vdi-destroy", "uuid=%s" % vdi)

        self.checkThenDestroySR()
        
        self.disableEthPort(1)
        self.sr = self.createSR(self.host)
        self.checkThenDestroySR()

        self.enableEthPort(1)
        self.sr = self.createSR(self.host)
        self.checkThenDestroySR()
