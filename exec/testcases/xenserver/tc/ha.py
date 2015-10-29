#
# XenRT: Test harness for Xen and the XenServer product family
#
# High Availability testcases
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, threading
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log, warning

class _HASmoketest(xenrt.TestCase):
    """Base class for HA smoketests"""
    STATEFILE_SR = "lvmoiscsi" # Set to lvmoiscsi / lvmohba etc
    VM_SR = None # None = use pool default SR, otherwise specify a uuid
    EXISTING_GUESTS = False # use existing guests
    NUMHOSTS = 3

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.pool = None
        self.guests = []

    def prepare(self, arglist=None):
        # Get pool object
        self.pool = self.getDefaultPool()
        if len(self.pool.getHosts()) != self.NUMHOSTS:
            raise xenrt.XRTError("Pool must have %u hosts (found %u)" %
                                 (self.NUMHOSTS, len(self.pool.getHosts())))

        # Find an appropriate SR to use
        srs = self.pool.master.getSRs(type=self.STATEFILE_SR)
        if len(srs) == 0:
            raise xenrt.XRTError("No SRs of type %s found" % (self.STATEFILE_SR))
        statefileSR = srs[0]
        self.statefileSR = statefileSR

        # Enable HA on the pool using the relevant SR
        self.pool.enableHA(srs=[statefileSR])

        # Set nTol to 1
        self.pool.setPoolParam("ha-host-failures-to-tolerate", 1)

        # Set up a debian VM per host, and protect them
        if self.EXISTING_GUESTS:
            for g in self.guests:
                g.setHAPriority(2)
        else:
            if self.VM_SR:
                vmSR = self.VM_SR
            else:
                vmSR = self.pool.getPoolParam("default-SR")
            for h in self.pool.getHosts():
                g = h.createGenericLinuxGuest(sr=vmSR)
                self.guests.append(g)
                g.setHAPriority(2)

    def run(self, arglist=None):
        # Steady state (wait 4 * max timeout and check things are still happy)
        xenrt.TEC().logdelimit("Waiting (4 * W) to verify HA steady state")
        self.pool.sleepHA("W",multiply=4)
        self.check()

        # 'Normal' host reboot
        xenrt.TEC().logdelimit("CLI host-reboot on a slave")
        self.pool.slaves.values()[0].cliReboot(evacuate=True)
        self.check()

        # Loss of heartbeats on slave
        xenrt.TEC().logdelimit("Blocking heartbeats on a slave")
        slave = self.pool.slaves.values()[1]
        slave.execdom0("touch /etc/xensource/xapi_block_startup")
        slave.blockHeartbeat()
        self.pool.haLiveset.remove(slave.getMyHostUUID())
        self.pool.sleepHA("W",multiply=4)
        self.check()

        xenrt.TEC().logverbose("Repairing slave so it rejoins pool")
        slave.waitForSSH(900, desc="host reboot after host fence")
        slave.blockHeartbeat(block=False,ignoreErrors=True)
        slave.execdom0("rm -f /etc/xensource/xapi_block_startup")
        slave.execdom0("rm -f /etc/xensource/boot_time_info_updated")
        slave.startXapi()
        time.sleep(120)
        self.pool.haLiveset.append(slave.getMyHostUUID())
        self.check()

        # Loss of xapi on master (to check failover etc)
        xenrt.TEC().logdelimit("Loss of xapi on master")
        self.pool.master.execdom0("touch /etc/xensource/xapi_block_startup")
        if self.pool.master.isCentOS7Dom0():
            self.pool.master.execdom0("systemctl stop xapi.service")
            self.pool.master.execdom0("systemctl disable xapi.service")
            self.pool.master.execdom0("mv /etc/init.d/xapi /etc/init.d/xapi.disabled")
        else:
            self.pool.master.execdom0("mv /etc/init.d/xapi "
                                      "/etc/init.d/xapi.disabled")
            self.pool.master.execdom0("/etc/init.d/xapi.disabled stop")
        oldMaster = self.pool.master
        self.pool.haLiveset.remove(self.pool.master.getMyHostUUID())
        self.pool.sleepHA("W",multiply=4)
        self.pool.findMaster(notCurrent=True, warnOnWait=True)
        self.check()

        xenrt.TEC().logverbose("Repairing old master so it rejoins pool")
        time.sleep(180)
        oldMaster.waitForSSH(300, desc="Old master boot after host fence")
        oldMaster.execdom0("rm -f /etc/xensource/xapi_block_startup")
        if oldMaster.isCentOS7Dom0():
            oldMaster.execdom0("mv /etc/init.d/xapi.disabled /etc/init.d/xapi")
            oldMaster.execdom0("systemctl enable xapi.service")
        else:
            oldMaster.execdom0("mv /etc/init.d/xapi.disabled "
                               "/etc/init.d/xapi")
        oldMaster.startXapi()
        time.sleep(120)
        self.pool.haLiveset.append(oldMaster.getMyHostUUID())
        self.check()

        # In-guest shutdown of protected VM
        xenrt.TEC().logdelimit("In-guest shutdown of protected VM")
        g = self.guests[0]
        origDomid = g.getDomid()
        g.execguest("(sleep 5 && /sbin/poweroff) > /dev/null 2>&1 < /dev/null &")
        time.sleep(180)
        # The guest may have moved host (if it has, then this is OK)
        origHost = g.host
        g.findHost(checkReachable=False)
        if g.host != origHost:
            g.check()
        else:
            # Same host, so get its domid
            newDomid = g.getDomid()
            if newDomid != origDomid:
                g.check()
            else:
                ld = g.host.listDomains(includeS=True)
                if ld[g.getUUID()][3] == g.host.STATE_SHUTDOWN:
                    raise xenrt.XRTFailure("In-guest shutdown of protected VM "
                                           "failed")
                raise xenrt.XRTError("In-guest shutdown of protected VM, guest "
                                     "didn't complete shutdown")

    def check(self):
        self.pool.checkHA()
        for g in self.guests:
            g.findHost()
            g.check()

    def postRun(self):
        # Try and disable HA if it's running
        if self.pool and self.pool.haEnabled:
            try:
                self.pool.disableHA(check=False)
                self.pool.syncDatabase()
            except:
                pass

class TC8144(_HASmoketest):
    """Verify HA operation on a pool of 8 hosts using iSCSI for HA and VMs."""
    NUMHOSTS = 8

class TC8149(_HASmoketest):
    """Verify HA operation on a pool of 9 hosts using iSCSI for HA and VMs."""
    NUMHOSTS = 9

class TC8192(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using multipathed fiberchannel for HA and VMs"""
    NUMHOSTS = 4
    STATEFILE_SR = "lvmohba"

class TCFCOEHAOperation(_HASmoketest):
    """Verify HA operation on a pool of 2 hosts using multipathed FCOE for HA and VMs"""
    NUMHOSTS = 4
    STATEFILE_SR = "lvmofcoe"

class TC13205(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using NFS for HA and VMs"""
    NUMHOSTS = 4
    STATEFILE_SR = "nfs"

class TC13208(_HASmoketest):
    """Verify HA operation on a pool of 8 hosts using NFS for HA and VMs"""
    NUMHOSTS = 8
    STATEFILE_SR = "nfs"
    
class TC8222(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using iSCSI reached via a dedicated storage bond"""
    NUMHOSTS = 4

class TC8455(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using iSCSI reached via a dedicated storage bond using static addresses"""
    NUMHOSTS = 4

class TC15639(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using iSCSI reached via a dedicated storage bond with 3 Nics"""
    NUMHOSTS = 4

class  TC15640(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using iSCSI reached via a dedicated storage bond using static addresses with 3 Nics"""
    NUMHOSTS = 4

class TC15641(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using iSCSI reached via a dedicated storage bond with 4 Nics"""
    NUMHOSTS = 4

class  TC15642(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using iSCSI reached via a dedicated storage bond using static addresses with 4 Nics"""
    NUMHOSTS = 4

class TC8223(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using multipathed iSCSI"""
    NUMHOSTS = 4
 
class TC8217(_HASmoketest):
    """Verify HA operation on a pool of 3 hosts with VMs on a VLAN"""
    NUMHOSTS = 3

class TC8206(_HASmoketest):
    """Verify HA operation on a 4 host pool upgraded from Miami"""
    NUMHOSTS = 4
    EXISTING_GUESTS = True

    def prepare(self, arglist=None):
        # Get the pool object
        pool = self.getDefaultPool()

        # Create the guests
        if self.VM_SR:
            vmSR = self.VM_SR
        else:
            vmSR = pool.getPoolParam("default-SR")
        for h in pool.getHosts():
            g = h.createBasicGuest(distro="rhel54", sr=vmSR)
            self.guests.append(g)
            g.shutdown()

        # Upgrade the pool
        pool = pool.upgrade()

        # Upgrade our guest objects (required due to HA changes in Boston CA-63151)
        newguests = []
        for g in self.guests:
            newg = pool.master.guestFactory()(g.name, host=g.host)
            g.populateSubclass(newg)
            newguests.append(newg)
        self.guests = newguests

        # Now start the VMs and sort out tools
        for g in self.guests:
            xenrt.TEC().progress("Upgrading VM %s" % (g.getName()))
            g.start()
            if g.windows:
                g.installDrivers()
            else:
                g.installTools()
            g.check()

        # Do the remaining prepare steps
        _HASmoketest.prepare(self, arglist=None)

class TC8214(_HASmoketest):
    """Verify HA operation on a pool of 16 hosts using iSCSI for HA and VMs with
       bonded management NICs."""
    NUMHOSTS = 16

class TC9169(_HASmoketest):
    """HA set up on a previous GA XenServer pool continues to operate after a rolling pool upgrade"""
    NUMHOSTS = 4
    EXISTING_GUESTS = True

    def prepare(self, arglist):
        # Get the guest objects
        for i in range(3):
            self.guests.append(xenrt.TEC().registry.guestGet("VM%u" % (i)))
        _HASmoketest.prepare(self, arglist)

    def run(self, arglist):
        # Disable HA
        xenrt.TEC().logverbose("Disabling HA before upgrade")
        self.pool.disableHA()

        # Perform a rolling pool upgrade
        xenrt.TEC().logverbose("Performing rolling pool upgrade...")
        self.pool = self.pool.upgrade(rolling=True)

        # Upgrade PV tools in guests
        xenrt.TEC().logverbose("Upgrading PV tools...")
        for g in self.guests:
            # The guest will have been migrated during the RPU...
            xenrt.TEC().logverbose("Finding and upgrading VM %s" % (g.getName()))
            g.findHost()
            if g.windows:
                g.installDrivers()
            else:
                g.installTools()
            g.check()

        # Re-enable HA
        self.pool.enableHA(srs=[self.statefileSR])

        # Perform the smoketest
        _HASmoketest.run(self, arglist)

class TC27205(_HASmoketest):
    """Verify HA operation on a pool of 4 hosts using SMAPIv3 NFS for HA and VMs"""
    NUMHOSTS = 4
    STATEFILE_SR = "rawnfs"

class TC7829(xenrt.TestCase):
    """Basic HA Sanity Test"""
    USE_ISCSI = True

    def __init__(self, tcid=None):
        self.pool = None
        xenrt.TestCase.__init__(self, tcid)

    def prepare(self, arglist=None):
        if arglist and len(arglist) > 0:
            self.pool = self.getPool(arglist[0])
        else:            
            self.pool = self.getDefaultPool()

        if self.USE_ISCSI:
            srs = self.pool.master.getSRs(type="lvmoiscsi")
            if len(srs) == 0:
                # If ISCSI SR is not present, creating one now.
                # Set up the iscsi guest
                host = self.pool.master
                guest = host.createGenericLinuxGuest(allowUpdateKernel=False)
                self.getLogsFrom(guest)
                iqn = guest.installLinuxISCSITarget()
                guest.createISCSITargetLun(0, 1024)

                # Set up the iSCSI SR
                sr = xenrt.lib.xenserver.ISCSIStorageRepository(host,"test-iscsi")
                lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" %
                                              (iqn, guest.getIP()))
                sr.create(lun,subtype="lvm",findSCSIID=True)

    def run(self, arglist=None):
        # Enable HA
        self.pool.enableHA(check=False)
        # Wait for > timeouts then check
        self.pool.sleepHA("W",multiply=3)
        self.pool.checkHA()
        # Disable HA
        self.pool.disableHA(check=False)
        # Wait for > timeouts then check
        self.pool.sleepHA("W",multiply=3)
        self.pool.checkHA()

class TCHASanityDefaultSR(TC7829):
    """Basic HA Sanity Test using default SR"""
    USE_ISCSI = False

class _RFInstall(xenrt.XRTThread):

    def __init__(self, host, setupISOs=False):
        self.host = host
        self.setupISOs = setupISOs
        self.exception = None
        xenrt.XRTThread.__init__(self)

    def run(self):
        try:
            self.host.resetToFreshInstall(setupISOs=self.setupISOs)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Exception while performing reset to fresh "
                                   "install on %s" % (self.host.getName()))
            self.exception = e

class _TileInstall(xenrt.XRTThread):

    def __init__(self, host, srUUID, workloads):
        self.host = host
        self.srUUID = srUUID
        self.workloads = workloads
        self.tile = None
        self.exception = None
        xenrt.XRTThread.__init__(self)

    def run(self):
        try:
            self.tile = xenrt.lib.xenserver.Tile(self.host,self.srUUID,
                                                 useWorkloads=self.workloads)
            self.tile.install()
        except Exception, e:
            xenrt.TEC().logverbose("Exception while performing a tile install")
            traceback.print_exc(file=sys.stderr)
            self.exception = e

class _HATest(xenrt.TestCase):
    LOAD = None
    WORKLOADS = True
    SF_STORAGE = ""

    def __init__(self, tcid=None):
        self.tiles = []
        self.pool = None
        self.sr = None
        self.guestSR = None
        self.hostsToPowerOn = []
        xenrt.TestCase.__init__(self, tcid)
        self.newMaster = False
        self.guestsToUninstallBeforeSRDestroy = []

    def resetToFreshInstall(self, hosts):
        # Reset the given hosts to a fresh install, giving the
        # first one setupISOs=True

        # Try to resurrect any unreachable hosts
        for h in hosts:
            try:
                # Unset the host's pool object in case it is still pointing at an HA
                # pool, as at that point checkReachable does weird things
                h.pool = None
                h.checkReachable()
            except:                
                # Host isn't reachable, try power cycling it a couple of times
                xenrt.TEC().warning("Host %s is unreachable at start of test" % (h.getName()))
                xenrt.TEC().logverbose("Attempting power cycle 1/2")
                h.machine.powerctl.cycle()
                try:                
                    h.waitForSSH(900, desc="First reboot attempt on dead host")
                    xenrt.TEC().logverbose("Host booted after one power cycle")
                except:
                    # Try again
                    xenrt.TEC().warning("Host %s still unreachable after 1 power cycle" % (h.getName()))
                    xenrt.TEC().logverbose("Attempting power cycle 2/2")
                    h.machine.powerctl.cycle()
                    # If this fails we want to bail out, so don't wrap in try/except
                    h.waitForSSH(900, desc="Second reboot attempt on dead host")

        rfInstalls = []
        rfInstalls.append(_RFInstall(hosts[0],setupISOs=True))
        for host in hosts[1:]:
            rfInstalls.append(_RFInstall(host))
        
        for rfi in rfInstalls:
            rfi.start()

        time.sleep(30)

        for rfi in rfInstalls:
            rfi.join()
            if rfi.exception:
                raise rfi.exception

    def configureHAPool(self, hosts, enable=True, iscsiLun=None, resetTFI=True):
        """Configure a pool with the specified hosts and enable HA"""
        try:
            if resetTFI:
                self.resetToFreshInstall(hosts)

            master = hosts[0]
            slaves = hosts[1:]
            pool = xenrt.lib.xenserver.poolFactory(master.productVersion)(master)
            self.pool = pool

            # Configure an SR
            # Try FC first
            fcsr = master.lookup("SR_FCHBA", "LUN0")
            scsiid = master.lookup(["FC", fcsr, "SCSIID"], None)
            if scsiid:
                # Verify the LUN is available on all hosts (CA-155371)
                for h in slaves:
                    if h.lookup(["FC", fcsr, "SCSIID"], None) != scsiid:
                        scsiid = None
                        break
            sr = None
            if self.SF_STORAGE.startswith("nfs"):
                # use NFS if specified
                #srs = pool.master.getSRs(type=self.SF_STORAGE)
                #if len(srs) > 0: 
                #    sr = srs[0]
                #else:
                # TODO Hack this to create an object every time for consistency.
                sr = self.createSharedNFSSR(pool.master, "NFS_SF_SR")
                self.sr = sr
                pool.addSRToPool(sr)
            elif self.SF_STORAGE.startswith("cifs"):
                share = xenrt.VMSMBShare()
                sr = xenrt.productLib(host=master).SMBStorageRepository(master, "CIFS-SR")
                self.sr = sr
                sr.create(share)
                pool.addSRToPool(sr)
            elif (scsiid and self.SF_STORAGE != "iscsi" and not iscsiLun):
                # Use FC
                sr = xenrt.lib.xenserver.FCStorageRepository(master, "fc", thin_prov=(self.tcsku=="thin"))
                self.sr = sr
                sr.create(scsiid)
                pool.addSRToPool(sr)
            elif self.SF_STORAGE != "fc" or iscsiLun:
                # Use ISCSI
                sr = xenrt.lib.xenserver.ISCSIStorageRepository(master, "iscsi", thin_prov=(self.tcsku=="thin"))
                self.sr = sr
                if iscsiLun:
                    sr.create(lun=iscsiLun, subtype="lvm", findSCSIID=True)
                else:
                    sr.create(subtype="lvm")
                pool.addSRToPool(sr)
            else:
                # Asked for FC but unable to do it
                raise xenrt.XRTError("Asked to use FC for StateFile but no "
                                     "luns found")

            if xenrt.TEC().lookup("OPTION_USE_STATEFILE_SR", False, boolean=True):
                self.guestSR = self.sr
            else:
                # Create an NFS SR to use for storing the VMs on (let us do fast
                # cloning etc). Do this here in case TCs need it            
                try:
                    self.guestSR = self.createSharedNFSSR(master, "TileSR")
                except:
                    xenrt.TEC().logverbose("Cannot create NFS SR, so using "
                                           "statefile SR instead")
                    self.guestSR = self.sr
            pool.setPoolParam("default-SR", self.guestSR.uuid)

            for s in slaves:
                pool.addHost(s)

            if self.LOAD and not xenrt.TEC().lookup("OPTION_NO_TILES", False, 
                                                    boolean=True):

                loadHosts = string.split(self.LOAD)
                for lh in loadHosts:
                    if lh == "master":
                        t = xenrt.lib.xenserver.Tile(master,self.guestSR.uuid,
                                                    useWorkloads=self.WORKLOADS)
                        self.tiles.append(t)
                        t.install()
                        t.start()
                    elif lh == "slaves":
                        stInstalls = []
                        for s in slaves:
                            t = _TileInstall(s,self.guestSR.uuid,self.WORKLOADS)
                            stInstalls.append(t)
                            t.start()
                        for st in stInstalls:
                            st.join()
                            if st.exception:
                                raise st.exception
                            self.tiles.append(st.tile)
                            st.tile.start()
                    elif lh == "protect":
                        for t in self.tiles:
                            for g in t.guests:
                                g.setHAPriority(2)
                                # Temporary hack to stop us checking memory...
                                g.memory = None

        except xenrt.XRTFailure, e:
            # This isn't a failure of the TC
            if e.data and "No space left on device" in e.data:
                self.pause("CA-138629 repro found", email="alex.brett@citrix.com")
            raise xenrt.XRTError(e.reason,e.data)

        if enable:
            pool.enableHA(srs=[self.sr.uuid])

        return pool

    def createSharedNFSSR(self, host, name):
        self.nfs = xenrt.ExternalNFSShare()
        nfs = self.nfs.getMount()
        r = re.search(r"([0-9\.]+):(\S+)", nfs)
        if not r:
            raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfs))
        if self.SF_STORAGE == "nfs4":
            sr = xenrt.lib.xenserver.NFSv4StorageRepository(host, name)
            sr.create(r.group(1), r.group(2))
        else:
            sr = xenrt.lib.xenserver.NFSStorageRepository(host, name)
            sr.create(r.group(1), r.group(2))
        self.nfssr = sr
        sr.check()
        host.addSR(sr)
        return sr

    def check(self, pool):
        # Check HA
        if pool.haEnabled:
            # We may have a new master
            if self.newMaster:
                # Require a new master
                pool.findMaster(notCurrent=True, warnOnWait=True)
            else:
                pool.findMaster()
            pool.checkHA()
        # Check the pool in general
        pool.check()
        # Check any tiles
        for t in self.tiles:
            t.check()

    def poweroff(self, host, cycle=False):
        try:
            host.execdom0("mount -o remount,barrier=1 /")
            host.execdom0("sync")
        except:
            pass
        if cycle:
            host.machine.powerctl.cycle()
        else:
            host.machine.powerctl.off()

    def preLogs(self):
        for h in self.hostsToPowerOn:
            h.machine.powerctl.on()

        if self.pool:
            for h in self.pool.getHosts():
                try:
                    h.waitForSSH(900, desc="Host boot for log collection")
                except:
                    # Try power cycling
                    h.machine.powerctl.cycle()
                    try:
                        h.waitForSSH(900, desc="Host boot for log collection")
                    except:
                        xenrt.TEC().warning("Host %s failed to boot for logs" %
                                            (h.getName()))

    def postRun(self):
        for t in self.tiles:
            try:
                t.cleanup(force=True)
            except:
                pass
        if self.pool:
            if self.pool.haEnabled:
                xenrt.TEC().logverbose("Attempting to disable HA")
                try:
                    cli = self.pool.getCLIInstance()
                    cli.execute("pool-ha-disable",timeout=600)
                    self.pool.haEnabled = False
                except:
                    xenrt.TEC().warning("Exception while disabling HA in postRun")
        for g in self.guestsToUninstallBeforeSRDestroy:
            xenrt.TEC().logverbose("Early uninstall of %s" % (g.getName()))
            try:
                if g.getState() != "DOWN":
                    g.shutdown(force=True)
            except Exception, e:
                xenrt.TEC().logverbose("Exception on resume or shutdown: %s" %
                                       (str(e)))
            try:
                g.uninstall()
            except Exception, e:
                xenrt.TEC().logverbose("Exception on uninstall: %s" %
                                       (str(e)))
        if self.sr:
            xenrt.TEC().logverbose("Attempting to release iSCSI/FC SR")
            try:
                self.sr.release()
            except:
                pass
        if self.nfs:
            try:
                self.nfs.release()
            except:
                pass
        if self.pool:
            for h in self.pool.getHosts():
                h.skipNextCrashdump = False

# Basic Configuration and Functional TCs

# 7.2.2.1
class TC7495(_HATest):    
    """Verify HA can be turned on when provided with a valid license"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])
        self.check(pool)

# 7.2.2.2
class TC7496(_HATest):
    """Verify HA cannot be turned on when provided with an invalid license"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        pool = self.configureHAPool([host],enable=False)
        cli = host.getCLIInstance()

        for sku in ["XE Server", "XE Express"]:
            host.license(sku=sku)
            allowed = False
            try:
                cli.execute("pool-ha-enable")
                allowed = True
            except:
                allowed = False
            if allowed:
                raise xenrt.XRTFailure("Allowed to enable HA with an invalid "
                                       "license (%s)" % (sku))

# 7.2.2.3
class TC7497(_HATest):
    """Determine if HA can be enabled for a one node pool"""

    def run(self, arglist=None):
        host = self.getDefaultHost()

        pool = self.configureHAPool([host])
        time.sleep(30)
        self.check(pool)

# 7.2.2.4 + 7.2.2.5 + 7.2.2.6
class TC7498(_HATest):
    """Verify HA can be enabled and disabled repeatably"""

    def run(self, arglist=None):
        loops = 5
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg,"=")
                if l[0] == "loops":
                    loops = int(l[1])

        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1],enable=False)

        currentLoop = 0

        try:
            while currentLoop < loops:
                xenrt.TEC().logdelimit("loop iteration %u" % (currentLoop))
                pool.enableHA()
                pool.sleepHA("T",multiply=2)
                self.check(pool)
                pool.disableHA()
                self.check(pool)
                currentLoop += 1
                time.sleep(30)
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" % 
                                (currentLoop, loops))

# 7.2.2.7
class TC7499(TC7495):
    """Verify StateFile can be located on shared FC storage"""
    SF_STORAGE = "fc"

# 7.2.2.8
class TC7500(TC7495):
    """Verify StateFile can be located on shared iSCSI storage"""
    SF_STORAGE = "iscsi"

class TC11795(TC7495):
    """Verify StateFile can be located on NFS storage"""
    SF_STORAGE = "nfs"
    
    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])
        self.check(pool)
        
class TC26902(TC7495):
    """Verify StateFile can be located on NFSv4 storage"""
    SF_STORAGE = "nfs4"
    
    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])
        self.check(pool)

class TCStateFileCIFS(TC7495):
    """Verify StateFile can be located on shared CIFS storage"""
    SF_STORAGE = "cifs"

class TC7935(_HATest):
    """Verify that pool-ha-enable honours the heartbeat-sr-uuids parameter"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.host.resetToFreshInstall(setupISOs=True)
        self.pool = xenrt.lib.xenserver.poolFactory(self.host.productVersion)(self.host)

        # Set up the following:
        # NFS SR
        self.nfsSR = self.createSharedNFSSR(self.host, "nfs")
        self.pool.addSRToPool(self.nfsSR)
        # iSCSI SR
        self.iscsiSR = xenrt.lib.xenserver.ISCSIStorageRepository(self.host, 
                                                                  "iscsi")
        self.iscsiSR.create(subtype="lvm")
        self.pool.addSRToPool(self.iscsiSR)

        # FC SR (if available)
        fcsr = self.host.lookup("SR_FCHBA", "LUN0")
        scsiid = self.host.lookup(["FC", fcsr, "SCSIID"], None)
        self.fcSR = None
        if scsiid:
            # Use FC
            self.fcSR = xenrt.lib.xenserver.FCStorageRepository(self.host, "fc")
            self.fcSR.create(scsiid)
            self.pool.addSRToPool(self.fcSR)

    def run(self, arglist=None):
    
        # 1) Attempt to pool-ha-enable with the uuid of an ISO SR
        
        xenrt.TEC().logdelimit('Testing HA with inappropriate storage '
            'specified for heartbeat')
        isoSR = self.host.getSRs(type="iso")[0]
        ok = False
        try:
            self.pool.enableHA(srs=[isoSR])
            ok = True
        except:
            xenrt.TEC().logverbose("Expected exception while attempting to "
                                   "enable HA using ISO SR")
        if ok:
            raise xenrt.XRTFailure("Able to enable HA using ISO SR")

        # 2) Attempt to pool-ha-enable with the uuid of a local storage SR
        localSR = self.host.getLocalSR()
        ok = False
        try:
            self.pool.enableHA(srs=[localSR])
            ok = True
        except:
            xenrt.TEC().logverbose("Expected exception while attempting to "
                                   "enable HA using local SR")
        if ok:
            raise xenrt.XRTFailure("Able to enable HA using local SR")

        # 3) Attempt pool-ha-enable with iSCSI, FC or NSF 
        
        xenrt.TEC().logdelimit('Testing HA with NFS/FC/iSCSI heartbeat storage')
        storage={'iSCSI': self.iscsiSR,  'NFS': self.nfsSR}
        order = ('NFS', 'iSCSI')
        if self.fcSR:
            storage['FC'] = self.fcSR
            order = ('NFS', 'FC', 'iSCSI')
        else:
            xenrt.TEC().comment("FC SR unavailable to test with")
            self.setResult(xenrt.RESULT_PARTIAL)
            
        for sr_type in order:
            xenrt.TEC().logverbose("Checking HA with heartbeat on %s storage" %
                sr_type)
            sr = storage[sr_type]
            self.pool.enableHA(srs=[sr.uuid])
            vdi = self.pool.haCommonConfig['statefileVDIs'][0]
            ha_statefile_sr = self.pool.master.getVDISR(vdi)
            if ha_statefile_sr != sr.uuid:
                xenrt.TEC().logverbose("Found statefile on SR %s, expected %s" %
                             (ha_statefile_sr, sr.uuid))
                raise xenrt.XRTFailure("pool-ha-enable ignored heartbeat-sr-"
                                     "uuids parameter for %s storage" % sr_type)
            self.pool.disableHA()

    def postRun(self):
        if self.pool:
            if self.pool.haEnabled:
                xenrt.TEC().logverbose("Attempting to disable HA")
                try:
                    cli = self.pool.getCLIInstance()
                    cli.execute("pool-ha-disable",timeout=600)
                    self.pool.haEnabled = False
                except:
                    xenrt.TEC().warning("Exception while disabling HA in postRun")
        if self.fcSR:
            try:
                self.fcSR.release()
            except:
                pass
        if self.iscsiSR:
            try:
                self.iscsiSR.release()
            except:
                pass
        _HATest.postRun(self)

# 7.2.3.1
class TC7501(_HATest):
    """Test that a different second node can be used in a pool"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")

        pool = self.configureHAPool([host0,host1])
        host2.resetToFreshInstall()
        self.sr.prepareSlave(pool.master, host2)

        # Disable HA
        pool.disableHA()
        # Remove the second node from the pool
        pool.eject(host1)
        # Add a different node to the pool
        pool.addHost(host2)
        # Enable HA again
        pool.enableHA()
        # Wait for twice the longest timeout value
        pool.sleepHA("T",multiply=2)
        self.check(pool)

# 7.2.3.2 + 7.2.3.3
class TC7502(_HATest):
    """Test that nodes can be added/removed one at a time to/from a pool"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        host3 = self.getHost("RESOURCE_HOST_3")

        pool = self.configureHAPool([host0,host1])
        host2.resetToFreshInstall()
        host3.resetToFreshInstall()
        self.sr.prepareSlave(pool.master, host2)
        self.sr.prepareSlave(pool.master, host3)

        # Add a third node to the pool
        pool.disableHA()
        pool.addHost(host2)
        pool.enableHA()
        pool.sleepHA("T",multiply=2)
        self.check(pool)

        # Add a fourth node to the pool
        pool.disableHA()
        pool.addHost(host3)
        pool.enableHA()
        pool.sleepHA("T",multiply=2)
        self.check(pool)

        # Remove the fourth node from the pool
        pool.disableHA()
        pool.eject(host3)
        pool.enableHA()
        pool.sleepHA("T",multiply=2)
        self.check(pool)

        # Remove the third node from the pool
        pool.disableHA()
        pool.eject(host2)
        pool.enableHA()
        pool.sleepHA("T",multiply=2)
        self.check(pool)

# 7.2.3.4 + 7.2.3.5
class TC7503(_HATest):
    """Test that nodes can be added/removed in groups to/from a pool"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        host3 = self.getHost("RESOURCE_HOST_3")

        pool = self.configureHAPool([host0,host1])
        host2.resetToFreshInstall()
        host3.resetToFreshInstall()
        self.sr.prepareSlave(pool.master,host2)
        self.sr.prepareSlave(pool.master,host3)

        # Add a third and fourth node to the pool
        pool.disableHA()
        pool.addHost(host2)
        pool.addHost(host3)
        pool.enableHA()
        pool.sleepHA("T",multiply=2)
        self.check(pool)

        # Remove the third and fourth nodes from the pool
        pool.disableHA()
        pool.eject(host3)
        pool.eject(host2)
        pool.enableHA()
        pool.sleepHA("T",multiply=2)
        self.check(pool)

# 7.2.3.6 + 7.2.3.7
class TC7504(TC7502):
    """Test that nodes can be added/removed to/from a pool under load"""
    LOAD = "master"

# 7.2.3.8
class TC7505(_HATest):
    """Test that a node can be added/removed several times"""

    def run(self, arglist=None):
        loops = 5
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg,"=")
                if l[0] == "loops":
                    loops = int(l[1])

        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")

        pool = self.configureHAPool([host0,host1])
        host2.resetToFreshInstall()
        self.sr.prepareSlave(pool.master, host2)

        currentLoop = 0

        try:
            while currentLoop < loops:
                xenrt.TEC().logdelimit("loop iteration %u" % (currentLoop))
                pool.disableHA()
                pool.addHost(host2)
                pool.enableHA()
                pool.sleepHA("T",multiply=2)
                self.check(pool)
                pool.disableHA()
                host2iqn = host2.getIQN()
                pool.eject(host2)
                # Re-set the IQN as it gets cleared by pool-eject
                special = {}
                special["IQN"] = host2iqn
                self.sr.prepareSlave(pool.master, host2, special=special)
                pool.enableHA()
                pool.sleepHA("T",multiply=2)
                self.check(pool)
                currentLoop += 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (currentLoop, loops))                

# Virtual Machine Protection TCs

# 7.2.4.1 + 7.2.4.2 + 7.2.4.3
class TC7506(_HATest):
    """Verify that protection can be turned on and off several times"""

    def run(self, arglist=None):
        loops = 5
        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg,"=")
                if l[0] == "loops":
                    loops = int(l[1])

        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])

        g = host0.createGenericLinuxGuest(sr=self.guestSR.uuid)
        self.guestsToUninstallBeforeSRDestroy.append(g)

        currentLoop = 0
        try:
            while currentLoop < loops:
                xenrt.TEC().logdelimit("loop iteration %u" % (currentLoop))
                g.setHAPriority(2)
                if not g.isProtected(): 
                    raise xenrt.XRTFailure("Guest not marked as protected after"
                                           " setting priority")
                g.setHAPriority(protect=False)
                if g.isProtected():
                    raise xenrt.XRTFailure("Guest still marked as protected "
                                           "after clearing priority")
                currentLoop += 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (currentLoop, loops))

# 7.2.4.4 + 7.2.4.5
class TC7507(_HATest):
    """Verify that protected VM is restarted on host failure"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        self.hostsToPowerOn.append(host0)
        self.hostsToPowerOn.append(host1)
        pool = self.configureHAPool([host0,host1])

        g = host0.createGenericLinuxGuest(sr=self.guestSR.uuid)
        self.guestsToUninstallBeforeSRDestroy.append(g)

        g.setHAPriority(2)
        g.memory = None

        # Attempt to workaround CA-139127 by allowing time for the pool-sync-database to go through
        xenrt.sleep(30)

        # Power off the host that g is running om
        self.poweroff(host0)

        # Wait for the specified time period
        pool.sleepHA("W",multiply=2)
        # Check the guest has come back up on host1
        pool.findMaster()
        g.host = host1
        g.check()

        # Power back on the first host
        host0.machine.powerctl.on()
        # Wait for it to boot up
        host0.waitForSSH(900)
        # Wait for xapi
        host0.waitForXapi(300, local=True)
        host0.waitForEnabled(300)
        # Check the pool is happy
        pool.check()

        # Power off the host that g is now running on
        self.poweroff(host1)

        # Wait for the specified time period
        pool.sleepHA("W",multiply=2)
        # Check the guest has come back up on host0
        pool.findMaster()
        g.host = host0
        g.check()

        # Power back on host1 for safety
        host1.machine.powerctl.on()
        # Wait for it to boot up
        host1.waitForSSH(900)
        host1.waitForXapi(300, local=True)

# 7.2.4.6 + 7.2.4.7
class TC7508(_HATest):
    """Verify that protection can be turned on for multiple VMs and they are
       restarted on node failure"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        self.hostsToPowerOn.append(host0)
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])

        t = xenrt.lib.xenserver.Tile(host0,self.guestSR.uuid,useWorkloads=False)
        t.install()

        for g in t.guests:
            self.guestsToUninstallBeforeSRDestroy.append(g)

        for g in t.guests:
            g.start()
            g.setHAPriority(2)
            g.memory = None

        # Attempt to workaround CA-139127 by allowing time for the pool-sync-database to go through
        xenrt.sleep(30)

        # Power off host0
        self.poweroff(host0)
        pool.haLiveset.remove(host0.getMyHostUUID())

        # Wait for the specified time period
        pool.sleepHA("W",multiply=2)

        # Check the guets have come back up on host1
        pool.findMaster()
        t.check()

        # Power on host0
        host0.machine.powerctl.on()
        host0.waitForSSH(900)

class TC8125(_HATest):
    """Internally-intiated shutdown of a protected guest should cause the guest
       to restart"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])

        # Start a VM and protect it
        guest = host0.createGenericLinuxGuest(sr=self.guestSR.uuid)
        self.guestsToUninstallBeforeSRDestroy.append(guest)
        guest.setHAPriority(2)
        
        # Get the VM's domid
        domid = guest.getDomid()

        # Ask the VM to shutdown from inside
        guest.execguest("(sleep 5 && /sbin/poweroff) > /dev/null "
                        "2>&1 </dev/null &")

        # wait for a while (give it a few minutes)
        time.sleep(180)

        # The guest may have moved host (if it has, then this is a pass)
        guest.findHost(checkReachable=False)
        if guest.host != host0:
            guest.check()
            return

        # Same host, so get its domid
        newDomid = guest.getDomid()       

        # The test passes if
        # * old domain ID has vanished from "list_domains"
        # * VM has been restarted by HA, has a new domain ID (possibly on a different host)
        if newDomid != domid:
            guest.check()
            return

        # The test fails if
        # * old domain ID is still present; domain is marked as "shutdown"
        if newDomid == domid:
            ld = guest.host.listDomains(includeS=True)
            if ld[guest.getUUID()][3] == guest.host.STATE_SHUTDOWN:
                raise xenrt.XRTFailure("CA-21205 internally-initiated shutdown "
                                       "of protected VM left unreaped domain")

        # Any other outcome probably indicates not enough time was left
        raise xenrt.XRTError("Test inconclusive, probably not enough time left "
                             "for guest shutdown")


# Pool Startup and Shutdown TCs

class TC7509(_HATest):
    """Verify that an HA-enabled pool continues to function when a non-master
       member without any protected VMs is shutdown cleanly"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        host3 = self.getHost("RESOURCE_HOST_3")
        pool = self.configureHAPool([host0,host1,host2,host3])

        self.hostsToPowerOn.append(host1)

        # Perform a clean shutdown of a non-master host
        host1.shutdown()

        self.check(pool)

class TC7511(_HATest):
    """Verify that an HA-enabled pool continues to function when a master member
       without any protected VMs is shutdown cleanly"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        host3 = self.getHost("RESOURCE_HOST_3")
        pool = self.configureHAPool([host0,host1,host2,host3])

        self.hostsToPowerOn.append(host0)

        # Perform a clean shutdown of the master
        host0.shutdown()
        self.newMaster = True

        self.check(pool)

class TC7514(_HATest):
    """Verify that a power-cycled node rejoins the pool automatically"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        host3 = self.getHost("RESOURCE_HOST_3")
        pool = self.configureHAPool([host0,host1,host2,host3])

        self.hostsToPowerOn.append(host1)

        # Perform a clean shutdown of a non-master host
        host1.shutdown()

        self.check(pool)

        # Now power cycle it so it turns back on
        host1.machine.powerctl.cycle()
        host1.waitForSSH(900, desc="Host bootup after clean shutdown")

        # Give it some time to finish booting
        time.sleep(180)

        # Add it back to the liveset we expect to see
        pool.haLiveset.append(host1.getMyHostUUID())

        self.check(pool)

# Base class for failure secnario testing
class _HAFailureTest(_HATest):
    # We want a tile of protected VMs per node
    WORKLOADS = False
    pool = None
    TEMPORARY = True
    TIMEOUT = None
    HOSTS = 4

    def prepare(self, arglist=None):
        if not self.TIMEOUT:
            raise xenrt.XRTError("Timeout not specified!")

        # Get our hosts, and create the pool
        hosts = []
        for i in range(self.HOSTS):
            hosts.append(self.getHost("RESOURCE_HOST_%u" % (i)))
        self.pool = self.configureHAPool(hosts)

        # Set the hosts not to restart xapi on bootup (otherwise we won't be
        # quick enough!)
        for h in hosts:
            h.execdom0("touch /etc/xensource/xapi_block_startup")

    def run(self, arglist=None):
        if self.TEMPORARY:
            if self.pool.getHATimeout(self.TIMEOUT) <= 10:
                xenrt.TEC().warning("Not testing temporary outage, timeout "
                                    "(%s: %u) is too small" % (self.TIMEOUT,
                                    self.pool.getHATimeout(self.TIMEOUT)))
            # Perform the failure(s)
            self.doFailures(metadata=False)
            # Wait for 10 seconds
            time.sleep(10)
            # Undo the failure(s)
            self.undoFailures()
            # Wait for thrice the timeout
            self.pool.sleepHA(self.TIMEOUT,multiply=3)
            # Make sure everythings happy
            # TODO: Check VMs haven't moved
            self.check(self.pool)

        # Now do the permanent failure
        self.doFailures()

        # Wait for thrice the timeout
        self.pool.sleepHA(self.TIMEOUT,multiply=3)

        # Check everything is in the 'correct' state
        self.check(self.pool)

    def doFailures(self, metadata=True):
        pass

    def undoFailures(self):
        pass

class _HAStatefileFailure(_HAFailureTest):
    TIMEOUT = "W"
    LOSE_MASTER = False
    LOSE_SLAVES = 0
    LOSE_ALL = False

    def doFailures(self, metadata=True, block=True):

        if self.LOSE_ALL:
            self.pool.blockAllStatefiles(block=block)
            # We expect all hosts to survive
            # But CA-25343 means quite often we get a crashdump from every host
            for h in self.pool.getHosts():
                h.skipNextCrashdump = True
            return

        if self.LOSE_MASTER:
            self.pool.master.blockStatefile(block=block)
            if metadata:
                self.pool.haLiveset.remove(self.pool.master.getMyHostUUID())
                self.newMaster = True
                self.pool.master.skipNextCrashdump = True

        slaves = self.pool.slaves.values()
        for i in range(self.LOSE_SLAVES):
            slaves[i].blockStatefile(block=block)
            if metadata:
                self.pool.haLiveset.remove(slaves[i].getMyHostUUID())
                slaves[i].skipNextCrashdump = True

    def undoFailures(self):
        self.doFailures(metadata=False, block=False)


class TC7685(_HAStatefileFailure):
    """Slave loss of statefile"""
    LOSE_SLAVES = 1
    
class TC13514(_HAStatefileFailure):
    """Slave loss of statefile for NFS SF"""
    LOSE_SLAVES = 1
    SF_STORAGE = "nfs"
    
class TC26904(_HAStatefileFailure):
    """Slave loss of statefile for NFSv4 SF"""
    LOSE_SLAVES = 1
    SF_STORAGE = "nfs4"
    
class TC7686(_HAStatefileFailure):
    """Master loss of statefile"""
    LOSE_MASTER = True
class TC7687(_HAStatefileFailure):
    """Multiple slave loss of statefile"""
    LOSE_SLAVES = 2
class TC7688(_HAStatefileFailure):
    """Master+slave loss of statefile"""
    LOSE_MASTER = True
    LOSE_SLAVES = 1
class TC7689(_HAStatefileFailure):
    """All hosts loss of statefile"""
    LOSE_ALL = True

    def postRun(self):
        # In case this test actually passed, unset the skipNextCrashdump field
        for h in self.pool.getHosts():
            h.skipNextCrashdump = False
        _HAStatefileFailure.postRun(self)

class TC7690(TC7685):
    """Slave loss of statefile (under load)"""
    WORKLOADS = True

class TC13542(TC7685):
    """Slave loss of statefile NFS"""
    SF_STORAGE = "nfs"

class TC7691(TC7686):
    """Master loss of statefile (under load)"""
    WORKLOADS = True

class TC13543(TC7686):
    """Master loss of statefile NFS"""
    SF_STORAGE = "nfs"

class TC7692(TC7687):
    """Multiple slave loss of statefile (under load)"""
    WORKLOADS = True

class TC13544(TC7687):
    """Multiple slave loss of statefile NFS"""
    SF_STORAGE = "nfs"
    
class TC7693(TC7688):
    """Master+slave loss of statefile (under load)"""
    WORKLOADS = True

class TC13515(TC7688):
    """Master+slave loss of statefile for NFS SF"""
    SF_STORAGE = "nfs"
    
class TC26905(TC7688):
    """Master+slave loss of statefile for NFSv4 SF"""
    SF_STORAGE = "nfs4"

class TC7694(TC7689):
    """All hosts loss of statefile (under load)"""
    WORKLOADS = True

class TC13541(TC7689):
    """All hosts loss of statefile"""
    SF_STORAGE = "nfs"
    
class TC26906(TC7689):
    """All hosts loss of statefile"""
    SF_STORAGE = "nfs4"

class _HAHeartbeatFailure(_HAFailureTest):
    TIMEOUT = "W"
    LOSE_MASTER = False
    LOSE_SLAVES = 0
    LOSE_ALL = False
    # Set to largest to create a partition with master in largest
    # Set to smallest to create a partition with master in smallest
    # Set to equal to create equal sided partition
    PARTITION = None

    def doFailures(self, metadata=True, block=True):

        if self.LOSE_ALL:
            self.pool.blockAllHeartbeats(block=block,enable=False)
            if metadata:
                # We expect the host with the lowest UUID to survive
                hosts = self.pool.getHosts()
                uuids = []
                for h in hosts:
                    uuids.append(h.getMyHostUUID())
                for h in hosts:
                    if h.getMyHostUUID() != min(uuids):
                        self.pool.haLiveset.remove(h.getMyHostUUID())
                        h.skipNextCrashdump = True
                    else:
                        if h != self.pool.master:
                            self.newMaster = True

        if self.LOSE_MASTER:
            self.pool.master.blockHeartbeat(block=block,enable=False)
            if metadata:
                self.pool.haLiveset.remove(self.pool.master.getMyHostUUID())
                self.pool.master.skipNextCrashdump = True
                self.newMaster = True

        slaves = self.pool.slaves.values()
        for i in range(self.LOSE_SLAVES):
            slaves[i].blockHeartbeat(block=block,enable=False)
            if metadata:
                self.pool.haLiveset.remove(slaves[i].getMyHostUUID())
                slaves[i].skipNextCrashdump = True

        if self.PARTITION == "largest":
            # Partition M S S | S S
            # We expect M S S to survive
            part1 = self.pool.slaves.values()[:2]
            part1.append(self.pool.master)
            part2 = self.pool.slaves.values()[2:]
            for h in part1:
                h.blockHeartbeat(fromHosts=part2,toHosts=part2,block=block,enable=False)
            for h in part2:
                h.blockHeartbeat(fromHosts=part1,toHosts=part1,block=block,enable=False)
                if metadata:
                    self.pool.haLiveset.remove(h.getMyHostUUID())
                    h.skipNextCrashdump = True
        elif self.PARTITION == "smallest":
            # Partition M S | S S S
            # We expect       S S S to survive
            part1 = self.pool.slaves.values()[:1]
            part1.append(self.pool.master)
            part2 = self.pool.slaves.values()[1:]
            for h in part1:
                h.blockHeartbeat(fromHosts=part2,toHosts=part2,block=block,enable=False)
                if metadata:
                    self.pool.haLiveset.remove(h.getMyHostUUID())
                    h.skipNextCrashdump = True
            for h in part2:
                h.blockHeartbeat(fromHosts=part1,toHosts=part1,block=block,enable=False)
            if metadata:
                self.newMaster = True
        elif self.PARTITION == "equal":
            # Partition M S | S S
            # We expect the pair containing the node with the smallest UUID to
            # survive
            if self.HOSTS != 4:
                raise xenrt.XRTError("Cannot create equal partition with "
                                     "%u hosts (need 4)" % (self.HOSTS))
            part1 = self.pool.slaves.values()[:1]
            part1.append(self.pool.master)
            part2 = self.pool.slaves.values()[1:]
            uuids = {}
            for h in self.pool.getHosts():
                uuids[h.getMyHostUUID()] = h
            smallest = min(uuids.keys())
            surviver = uuids[smallest]

            # Make sure part1 is the surviving partition
            if not surviver in part1:
                partT = part1
                part1 = part2
                part2 = partT

            if metadata and not self.pool.master in part1:
                self.newMaster = True

            for h in part1:
                h.blockHeartbeat(fromHosts=part2,toHosts=part2,block=block,enable=False)
            for h in part2:
                h.blockHeartbeat(fromHosts=part1,toHosts=part1,block=block,enable=False)
                if metadata:
                    self.pool.haLiveset.remove(h.getMyHostUUID())
                    h.skipNextCrashdump = True

        if block:
            self.pool.enableHeartbeatBlocks()

    def undoFailures(self):
        # Disable them quickly
        self.pool.disableHeartbeatBlocks()
        # Go through and delete the actual rules
        self.doFailures(metadata=False,block=False)


class TC7695(_HAHeartbeatFailure):
    """Slave loss of heartbeats"""
    LOSE_SLAVES = 1
class TC7696(_HAHeartbeatFailure):
    """Master loss of heartbeats"""
    LOSE_MASTER = True
class TC7697(_HAHeartbeatFailure):
    """Multiple slave loss of heartbeats"""
    LOSE_SLAVES = 2
class TC7698(_HAHeartbeatFailure):
    """Master+slave loss of heartbeats"""
    LOSE_MASTER = True
    LOSE_SLAVES = 1
class TC13516(_HAHeartbeatFailure):
    """Master+slave loss of heartbeats for NFS SF"""
    LOSE_MASTER = True
    LOSE_SLAVES = 1   
    SF_STORAGE = "nfs"
    
class TC26907(_HAHeartbeatFailure):
    """Master+slave loss of heartbeats for NFSv4 SF"""
    LOSE_MASTER = True
    LOSE_SLAVES = 1   
    SF_STORAGE = "nfs4"

class TC7699(_HAHeartbeatFailure):
    """All hosts loss of heartbeats"""
    LOSE_ALL = True
class TC7700(_HAHeartbeatFailure):
    """Master in largest partition"""
    PARTITION = "largest"
    HOSTS = 5
class TC7701(_HAHeartbeatFailure):
    """Master in smallest partition"""
    PARTITION = "smallest"
    HOSTS = 5
class TC7702(_HAHeartbeatFailure):
    """Equal partitions"""
    PARTITION = "equal"

class TC7703(TC7695):
    """Slave loss of heartbeats (under load)"""
    WORKLOADS = True

class TC13545(TC7695):
    """Slave loss of heartbeats NFS"""
    SF_STORAGE = "nfs"

class TC7704(TC7696):
    """Master loss of heartbeats (under load)"""
    WORKLOADS = True

class TC13546(TC7696):
    """Master loss of heartbeats NFS"""
    SF_STORAGE = "nfs"

class TC7705(TC7697):
    """Multiple slave loss of heartbeats (under load)"""
    WORKLOADS = True

class TC13547(TC7697):
    """Multiple slave loss of heartbeats NFS"""
    SF_STORAGE = "nfs"

class TC7706(TC7698):
    """Master+slave loss of heartbeats (under load)"""
    WORKLOADS = True

class TC13548(TC7698):
    """Master+slave loss of heartbeats NFS"""
    SF_STORAGE = "nfs"

class TC7707(TC7699):
    """All hosts loss of heartbeats (under load)"""
    WORKLOADS = True

class TC13549(TC7699):
    """All hosts loss of heartbeats NFS"""
    SF_STORAGE = "nfs"

class TC7708(TC7700):
    """Master in largest heartbeat partition (under load)"""
    WORKLOADS = True

class TC13550(TC7700):
    """Master in largest heartbeat partition NFS"""
    SF_STORAGE = "nfs"

class TC7709(TC7701):
    """Master in smallest heartbeat partition (under load)"""
    WORKLOADS = True

class TC13551(TC7701):
    """Master in smallest heartbeat partition NFS"""
    SF_STORAGE = "nfs"

class TC7710(TC7702):
    """Equal heartbeat partitions (under load)"""
    WORKLOADS = True

class TC13552(TC7702):
    """Equal heartbeat partitions NFS"""
    SF_STORAGE = "nfs"


class _HAHostFailure(_HAFailureTest):
    TIMEOUT = "W"
    LOSE_MASTER = False
    LOSE_SLAVES = 0
    TEMPORARY = False # We can't have a temporary host failure!

    def doFailures(self):
        downHosts = []
        if self.LOSE_MASTER:
            if not self.pool.master in self.hostsToPowerOn:
                self.hostsToPowerOn.append(self.pool.master)
            self.poweroff(self.pool.master)
            self.pool.haLiveset.remove(self.pool.master.getMyHostUUID())
            self.newMaster = True
            downHosts.append(self.pool.master)

        slaves = self.pool.slaves.values()
        for i in range(self.LOSE_SLAVES):
            if not slaves[i] in self.hostsToPowerOn:
                self.hostsToPowerOn.append(slaves[i])
            self.poweroff(slaves[i])
            self.pool.haLiveset.remove(slaves[i].getMyHostUUID())
            downHosts.append(slaves[i])

        # Allow some time for IPMI actions etc to happen
        xenrt.sleep(15)

        # Verify that all the hosts we've powered down are actually down (CA-174182)
        for h in downHosts:
            xenrt.TEC().logverbose("Verifying host %s is down" % h.getName())
            if h.checkAlive():
                raise xenrt.XRTError("Host %s still reachable after being powered down" % h.getName())


class TC7711(_HAHostFailure):
    """Loss of slave"""
    LOSE_SLAVES = 1
class TC7712(_HAHostFailure):
    """Loss of master"""
    LOSE_MASTER = True
class TC13518(_HAHostFailure):
    """Loss of master for NFS SF"""
    LOSE_MASTER = True    
    SF_STORAGE = "nfs"

class TC26910(_HAHostFailure):
    """Loss of master for NFSv4 SF"""
    LOSE_MASTER = True    
    SF_STORAGE = "nfs4"

class TC7713(_HAHostFailure):
    """Loss of multiple slaves"""
    LOSE_SLAVES = 2
class TC7714(_HAHostFailure):
    """Loss of master+slave"""
    LOSE_MASTER = True
    LOSE_SLAVES = 1

class TC7715(TC7711):
    """Loss of slave (under load)"""
    WORKLOADS = True
class TC13517(TC7711):
    """Loss of slave for NFS SF"""
    SF_STORAGE = "nfs"

class TC26908(TC7711):
    """Loss of slave for NFSv4 SF"""
    SF_STORAGE = "nfs4"

class TC7716(TC7712):
    """Loss of master (under load)"""
    WORKLOADS = True

class TC13555(TC7712):
    """Loss of master NFS"""
    SF_STORAGE = "nfs"

class TC7717(TC7713):
    """Loss of multiple slaves (under load)"""
    WORKLOADS = True

class TC13556(TC7713):
    """Loss of multiple slaves NFS"""
    SF_STORAGE = "nfs"

class TC7718(TC7714):
    """Loss of master+slave (under load)"""
    WORKLOADS = True
class TC13519(TC7714):
    """Loss of master+slave for NFS SF"""
    SF_STORAGE = "nfs"
class TC26911(TC7714):
    """Loss of master+slave for NFSv4 SF"""
    SF_STORAGE = "nfs4"

# Two node pool failure scenarios
class TC7719(_HAStatefileFailure):
    """Slave loss of statefile in two node pool"""
    LOSE_SLAVES = 1
    HOSTS = 2
class TC7720(_HAStatefileFailure):
    """Master loss of statefile in two node pool"""
    LOSE_MASTER = True
    HOSTS = 2
class TC7721(_HATest):
    """Loss of heartbeats in two node pool"""
    WORKLOADS = False

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])

        for h in pool.getHosts():
            h.execdom0("touch /etc/xensource/xapi_block_startup")

        # Kill heartbeats on one host (shouldn't matter which!)
        host0.blockHeartbeat()
        # Sleep for 10 seconds
        time.sleep(10)
        # Unblock
        host0.blockHeartbeat(block=False)

        # Wait three times the timeout
        pool.sleepHA("W",multiply=3)
        self.check(pool)

        # Block again
        host0.blockHeartbeat()
        # Wait three times the timeout
        pool.sleepHA("W",multiply=3)       
        
        # The correct behaviour is for the host with the lowest UUID to survive
        if host0.getMyHostUUID() < host1.getMyHostUUID():
            # host 0 should survive
            pool.haLiveset.remove(host1.getMyHostUUID())
        else:
            # host 1 should survive
            pool.haLiveset.remove(host0.getMyHostUUID())
            self.newMaster = True

        self.check(pool)
class TC13520(TC7721):
    """Loss of heartbeats in two node pool for NFS SF"""
    SF_STORAGE = "nfs"
class TC7722(_HAHostFailure):
    """Loss of slave in two node pool"""
    LOSE_SLAVES = 1
    HOSTS = 2
class TC7723(_HAHostFailure):
    """Loss of master in two node pool"""
    LOSE_MASTER = True
    HOSTS = 2

class TC7724(TC7719):
    """Slave loss of statefile in two node pool (under load)"""
    WORKLOADS = True
    
class TC13557(TC7719):
    """Slave loss of statefile in two node pool NFS"""
    SF_STORAGE = "nfs"
    
class TC7725(TC7720):
    """Master loss of statefile in two node pool (under load)"""
    WORKLOADS = True

class TC13558(TC7720):
    """Master loss of statefile in two node pool NFS"""
    SF_STORAGE = "nfs"

class TC7726(TC7721):
    """Loss of heartbeats in two node pool (under load)"""
    WORKLOADS = True

class TC13521(TC7721):
    """Loss of heartbeats in two node pool for NFS SF"""
    SF_STORAGE = "nfs"

class TC7727(TC7722):
    """Loss of slave in two node pool (under load)"""
    WORKLOADS = True

class TC13559(TC7722):
    """Loss of slave in two node pool NFS """
    SF_STORAGE = "nfs"


class TC7728(TC7723):
    """Loss of master in two node pool (under load)"""
    WORKLOADS = True

class TC13560(TC7723):
    """Loss of master in two node pool NFS"""
    SF_STORAGE = "nfs"

# Host Software Failure Scenarios
class _HAXapiFailure(_HATest):
    WORKLOADS = False
    pool = None
    MASTER = False

    def prepare(self, arglist=None):
        # Make a 4-node pool
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        host3 = self.getHost("RESOURCE_HOST_3")
        self.pool = self.configureHAPool([host0,host1,host2,host3])

    def run(self, arglist=None):
        # Temporary failure:

        # Just do a xapi stop on the relevant host
        if self.MASTER:
            self.pool.master.execdom0("service xapi stop")
        else:
            self.pool.slaves.values()[0].execdom0("service xapi stop")

        # Wait, then check on the relevant host uptime (i.e. verify it
        # didn't fence and reboot), and that xapi is running
        self.pool.sleepHA("X",multiply=2)
        # TODO: Check uptime
        self.check(self.pool)

        # Now do a permanent failure
        disabledHost = None
        try:
            if self.MASTER:
                self.pool.master.execdom0("touch "
                                          "/etc/xensource/xapi_block_startup")
                disabledHost = self.pool.master
                if self.pool.master.isCentOS7Dom0():
                    self.pool.master.execdom0("systemctl stop xapi.service")
                    self.pool.master.execdom0("systemctl disable xapi.service")
                else:
                    self.pool.master.execdom0("mv /etc/init.d/xapi "
                                              "/etc/init.d/xapi.disabled")
                    self.pool.master.execdom0("/etc/init.d/xapi.disabled stop")
                self.pool.haLiveset.remove(self.pool.master.getMyHostUUID())
                self.pool.master.skipNextCrashdump = True
                self.newMaster = True
            else:
                h = self.pool.slaves.values()[0]
                h.execdom0("touch /etc/xensource/xapi_block_startup")
                disabledHost = h
                if h.isCentOS7Dom0():
                    h.execdom0("systemctl stop xapi.service")
                    h.execdom0("systemctl disable xapi.service")
                else:
                    h.execdom0("mv /etc/init.d/xapi "
                               "/etc/init.d/xapi.disabled")
                    h.execdom0("/etc/init.d/xapi.disabled stop")
                self.pool.haLiveset.remove(h.getMyHostUUID())
                h.skipNextCrashdump = True
    
            self.pool.sleepHA("X",multiply=3)
            self.check(self.pool)
        finally:
            if disabledHost:
                try:
                    disabledHost.waitForSSH(900, desc="Host boot to fix xapi")
                    if disabledHost.isCentOS7Dom0():
                        disabledHost.execdom0("systemctl enable xapi.service")
                    else:
                        disabledHost.execdom0("mv /etc/init.d/xapi.disabled "
                                              "/etc/init.d/xapi")
                except:
                    xenrt.TEC().warning("Unable to restore xapi binary!")

class TC7729(_HAXapiFailure):
    """Xapi failure on a slave"""
    pass

class TC13561(_HAXapiFailure):
    """Xapi failure on a slave NFS"""
    SF_STORAGE = "nfs"

class TC7730(_HAXapiFailure):
    """Xapi failure on a master"""
    MASTER = True

class TC13562(_HAXapiFailure):
    """Xapi failure on a master NFS"""
    MASTER = True
    SF_STORAGE = "nfs"
    
# Load & Complex Failure Testing
class TC7731(_HATest):
    """Verify that pool properly reacts if after global loss of statefile, a
       further failure (heartbeat loss to one node) occurs"""

    WORKLOADS = False

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        host3 = self.getHost("RESOURCE_HOST_3")
        self.pool = self.configureHAPool([host0,host1,host2,host3])

        for h in self.pool.getHosts():
            h.execdom0("touch /etc/xensource/xapi_block_startup")

        # Block all statefile access
        self.pool.blockAllStatefiles()
        # Wait twice the timeout then check that it's happy
        self.pool.sleepHA("T2",multiply=2)
        self.pool.check() # No point checking HA, as statefile is old

        # Block heartbeats on a node
        host2.blockHeartbeat()

        # Wait appropriate amount of time
        self.pool.sleepHA("T1",multiply=2)
        # All nodes should be self fenced
        self.pool.haLiveset = []
        for h in self.pool.getHosts():
            h.skipNextCrashdump = True
        self.pool.checkHA()

class TC13563(TC7731):
    """Verify that pool properly reacts if after global loss of statefile, a
       further failure (heartbeat loss to one node) occurs NFS"""
    SF_STORAGE = "nfs"

class _Overcommit(_HATest):
    HOSTS = 2
    OPS = 60
    NTOLS = []
    EXISTING_POOL = False

    def __init__(self, tcid=None):
        self.ops = [ "newVM",
                     "delVM",
                     "disableHost",
                     "pbdUnplug",
                     "failHost" ]
        self.guest = None
        self.guests = []
        self.hosts = {}
        self.nTol = 0
        self.hostMemory = 0
        _HATest.__init__(self, tcid)

    def prepare(self, arglist=None):

        if self.EXISTING_POOL:
            # We expect a pool with the correct number of hosts, and a
            # single iSCSI SR
            self.pool = self.getDefaultPool()
            if len(self.pool.getHosts()) != self.HOSTS:
                raise xenrt.XRTError("Expecting %u hosts in pool, found %u" %
                                     (self.HOSTS, len(self.pool.getHosts())))
            for h in self.pool.getHosts():
                self.hostsToPowerOn.append(h)
                self.hosts[h] = True

            if self.SF_STORAGE and self.SF_STORAGE == "nfs":
                srtype = "nfs"
            else:
                srtype = "lvmoiscsi"

            srs = self.pool.master.getSRs(type=srtype)
            if len(srs) < 1:
                raise xenrt.XRTError("Couldn't find an %s SR" % (srtype))
            sruuid = srs[0]
            for sr in self.pool.master.srs.values():
                if sr.uuid == sruuid:
                    self.sr = sr
                    self.guestSR = sr
                    break
            if not self.sr:
                raise xenrt.XRTError("Couldn't find SR %s in master's srs" %
                                     (sruuid))

            self.pool.enableHA(srs=[sruuid])       
        else:
            # Create a pool of n hosts, with HA enabled
            for i in range(self.HOSTS):
                h = self.getHost("RESOURCE_HOST_%u" % (i))
                self.hostsToPowerOn.append(h)
                self.hosts[h] = True

            self.configureHAPool(self.hosts.keys())

        # Create a template debian guest, and preCloneTailor it
        self.guest = self.pool.master.createGenericLinuxGuest(sr=self.guestSR.uuid)
        self.guest.preCloneTailor()
        self.guest.shutdown()

        # Set self.hostMemory to the memory available for VMs on each host (we assume they are 
        # identical)
        self.hostMemory = int(self.hosts.keys()[1].getHostParam("memory-free")) / 1048576
  
        if self.hostMemory == 0:
            raise xenrt.XRTFailure("Host free memory reported by Xapi is 0")

    def run(self, arglist=None):
        opCount = self.OPS

        if len(self.NTOLS) == 0:
            # We vary Ntol from 1 - (self.HOSTS - 1)
            ntols = range(1,self.HOSTS)
        else:
            ntols = self.NTOLS

        for nt in ntols:
            # Try for 3 VMs per host
            initialCount = self.HOSTS * 3
            ntol = nt
            if ntol == -1:
                # Use the maximum the pool will let us use
                xenrt.TEC().logverbose("Finding maximum allowed nTol")
                # We want to create initialCount VMs
                # Add up total memory
                memoryNeeded = self.guest.memory * initialCount
                # See how many hosts we need
                hostsNeeded = self.roundUpDivide(memoryNeeded,self.hostMemory)
                ntol = self.HOSTS - hostsNeeded # Set nTol to this number
                # Make sure nTol is at least half the number of hosts
                # (this is OK as we will just start fewer VMs if we have to)
                if ntol < (self.HOSTS / 2):
                    ntol = (self.HOSTS / 2)
            xenrt.TEC().logdelimit("Running with ntol %u" % (ntol))           
            self.nTol = ntol
            self.pool.setPoolParam("ha-host-failures-to-tolerate",ntol)
            # Install 3 VMs per host (as long as this doesn't breach nTol)...
            xenrt.TEC().logverbose("Installing %u initial VMs" % (initialCount))
            hIndex = 0
            for i in range(initialCount):
                if not self.checkAllowed(self.guest.memory):
                    xenrt.TEC().comment("Only installed %u initial VMs as more "
                                        "would overcommit us" % (i))
                    break
                g = self.guest.cloneVM()
                g.host = self.hosts.keys()[hIndex]
                g.start()
                self.guests.append(g)
                g.setHAPriority(2)
                hIndex += 1
                if hIndex == self.HOSTS:
                    hIndex = 0
            for i in range(opCount):
                xenrt.TEC().logverbose("Operation %u/%u" % (i,opCount))
                op = self.ops[random.randint(0, len(self.ops) - 1)]
                self.getHAVariables()
                result = self.runSubcase(op, (), op, "%u_%u_%s" % (ntol,i,op))
                self.getHAVariables()
                if result != xenrt.RESULT_PASS and \
                   result != xenrt.RESULT_SKIPPED:
                    raise xenrt.XRTFailure("%u_%u_%s failed" % (ntol,i,op))
                # Poll to make sure all VMs are up
                for g in self.guests:
                    if not g.findHost():
                        raise xenrt.XRTFailure("Guest failed to reappear",
                                               g.getName())
                time.sleep(15)
            # Clean up
            for h in self.hosts.keys():
                if not self.hosts[h]:
                    h.machine.powerctl.on()
                    h.waitForSSH(900)
                    h.waitForXapi(300, local=True)
                    h.waitForEnabled(600)
                    self.hosts[h] = True
                if not h.getMyHostUUID() in self.pool.haLiveset:
                    self.pool.haLiveset.append(h.getMyHostUUID())
            for g in self.guests:
                g.setHAPriority(protect=False)
                g.shutdown()
                g.uninstall()
            self.guests = []            

    def newVM(self):
        # (Try to) add a new 512M VM

        # Clone (this should work regardless)
        g = self.guest.cloneVM(name=xenrt.randomGuestName())

        # Start (this may or may not work)
        if self.checkAllowed(g.memory):
            # We expect it to work
            xenrt.TEC().logverbose("newVM - should be allowed")
            # Find a host which has memory available (CA-19507)
            g.host = None
            for h in self.hosts.keys():
                if self.hosts[h]:
                    if (int(h.getHostParam("memory-free")) / 1048576) > g.memory:
                        g.host = h
                        break
            if not g.host:
                raise xenrt.XRTSkip("No host with enough memory found")
            g.start()
            self.guests.append(g)
            g.setHAPriority(2)
        else:
            # We expect it to fail
            xenrt.TEC().logverbose("newVM - should be refused")
            allowed = False
            try:
                g.start()
                g.setHAPriority(2)
                allowed = True
                g.setHAPriority(protect=False)
                g.shutdown()
            except:
                pass
            if g.getState() == "UP":
                g.shutdown()
            g.uninstall()
            if allowed:
                raise xenrt.XRTFailure("Allowed to start a new VM which should "
                                       "have been blocked")

    def delVM(self):
        # Delete a VM (assuming one is available) - this should always work
        if len(self.guests) == 0:
            raise xenrt.XRTSkip("delVM - None available to delete")

        g = self.guests[random.randint(0, len(self.guests) - 1)]
        xenrt.TEC().logverbose("delVM - Removing guest %s" % (g.getName()))
        g.setHAPriority(protect=False)
        g.shutdown()
        g.uninstall()
        self.guests.remove(g)

    def disableHost(self):
        # Attempt to evacuate+disable a (slave) host
        # Find a slave
        host = None
        for h in self.hosts.keys():
            if self.hosts[h] and h != self.pool.master:
                host = h
                break
        if not host:
            raise xenrt.XRTSkip("No suitable host found to disable")

        xenrt.TEC().logverbose("disableHost - using %s" % (host.getName()))

        # Evacuate the host to get VMs off it
        try:
            # This should work as long as theres capacity in the pool
            host.evacuate()
        except:
            raise xenrt.XRTSkip("Unable to evacuate the host")

        # Try and disable it...
        if self.checkAllowed(0,loseHosts=1):
            # Should work correctly
            host.disable()
            # Re-enable
            host.enable()            
        else:
            # Should be blocked
            allowed = False
            try:
                host.disable()
                allowed = True
                host.enable()
            except:
                pass
            if allowed:
                raise xenrt.XRTFailure("Allowed to disable a host when "
                                       "operation should have been blocked")

    def pbdUnplug(self):
        # If we have a host with no VMs running, then attempt to unplug a PBD on
        # the Tile SR
        host = None
        for h in self.hosts.keys():
            if self.hosts[h]:
                suitable = True
                for g in self.guests:
                    if g.host == h:
                        suitable = False
                        break
                if suitable:
                    host = h
                    break
        if not host:
            raise xenrt.XRTSkip("No suitable host found to pbd-unplug")

        xenrt.TEC().logverbose("pbdUnplug - using %s" % (host.getName()))
        args = []
        args.append("host-uuid=%s" % (host.getMyHostUUID()))
        args.append("sr-uuid=%s" % (self.guestSR.uuid))
        pbd = host.minimalList("pbd-list", args=string.join(args))[0]
    
        cli = host.getCLIInstance()
        # We only expect this to work if there's no VMs using the SR (CA-20019)
        # and if we aren't using the SR for the statefile...
        if len(self.guests) == 0 and self.sr != self.guestSR:
            cli.execute("pbd-unplug uuid=%s" % (pbd))
            cli.execute("pbd-plug uuid=%s" % (pbd))
        else:
            allowed = False
            try:
                cli.execute("pbd-unplug uuid=%s" % (pbd))
                allowed = True
                cli.execute("pbd-plug uuid=%s" % (pbd))
            except:
                pass
            if allowed:
                raise xenrt.XRTFailure("Allowed to pbd-unplug SR from a host "
                                       "when operation should be blocked")

    def failHost(self):
        # If we've got a failed host already, restore it, otherwise fail a new one
        for h in self.hosts.keys():
            if not self.hosts[h]:
                xenrt.TEC().logverbose("failHost - restoring %s" % (h.getName()))
                h.machine.powerctl.on()
                h.waitForSSH(900)
                h.waitForXapi(300, local=True)
                h.waitForEnabled(600)
                self.hosts[h] = True
                self.pool.haLiveset.append(h.getMyHostUUID())
                time.sleep(300)
                return

        # Randomly pick a host to fail
        hIndex = random.randint(0, len(self.hosts.keys()) - 1)
        h = self.hosts.keys()[hIndex]
        xenrt.TEC().logverbose("failHost - failing %s" % (h.getName()))
        self.hosts[h] = False
        self.poweroff(h)
        self.pool.haLiveset.remove(h.getMyHostUUID())
        self.pool.sleepHA("W", multiply=2)
        # Did we kill the master?
        if self.pool.master == h:
            self.pool.findMaster(notCurrent=True, warnOnWait=True)

    def getCurrentUsage(self):
        # Figure out how much RAM we're using (in MB)
        currentUsage = 0
        for g in self.guests:
            currentUsage += g.memory
        return currentUsage

    def checkAllowed(self, difference, loseHosts=0):
        # Decide whether the operation should be allowed
        # Work out current usage
        currentUsage = self.getCurrentUsage()
        liveHosts = self.getLiveHosts()

        if liveHosts < len(self.hosts.keys()):
            # Op will be allowed as long as it won't further reduce the # of
            # failures we can tolerate
            # Work out how many failures we can currently tolerate
            cTol = liveHosts - self.roundUpDivide(currentUsage,self.hostMemory)
            if cTol > self.nTol:
                cTol = self.nTol
            # We need to check that AFTER the op, we could still tolerate nTol
            # failures, i.e. assume a full host's worth of memory failed...
            # See what happens with this change
            wTol = (liveHosts - loseHosts) - self.roundUpDivide((currentUsage + difference),self.hostMemory)
            if wTol > self.nTol:
                wTol = self.nTol

            if wTol < cTol:
                # We'd support fewer failures, op should be blocked
                if currentUsage == 0 and cTol == liveHosts and wTol == 1 and loseHosts > 0:
                    # Xapi requires at least one host live, even if no VMs are running,
                    # as such in this situation the operation will be allowed because although
                    # we think it would reduce our failure capacity to 1, actually Xapi will
                    # already think it's cTol is 1.
                    return True
                return False
            else:
                # Won't change failure count, so will be allowed
                return True

        if currentUsage > (self.hostMemory * (liveHosts - self.nTol)):
            # Already overcommitted, so operation should be allowed
            return True
        elif (currentUsage + difference) > (self.hostMemory * ((liveHosts - loseHosts) - self.nTol)):
            # Would make us overcommitted, so should be blocked
            return False
        else:
            # Won't make us overcommitted, so allowed
            return True

    def roundUpDivide(self,a,b):
        # Return a/b rounded UP
        floated = float(a) / float(b)
        result = int(floated)
        remainder = floated - result
        if remainder > 0:
            result += 1
        return result

    def getLiveHosts(self):
        liveHosts = 0
        for h in self.hosts.keys():
            if self.hosts[h]:
                liveHosts += 1
        return liveHosts

    def getHAVariables(self):
        # Get the HA variables and logverbose them
        nTol = self.pool.getPoolParam("ha-host-failures-to-tolerate")
        planFor = self.pool.getPoolParam("ha-plan-exists-for")
        overCommitted = self.pool.getPoolParam("ha-overcommitted")
        xenrt.TEC().logverbose("Pool params -> ntol: %s, plan for: %s, "
                               "overcommitted: %s. %u guests on %u/%u hosts." % 
                               (nTol,planFor,overCommitted,len(self.guests),
                                self.getLiveHosts(),len(self.hosts)))

class TC8008(_Overcommit):
    """Test overcommit logic in a 3 host pool"""
    HOSTS = 3
    
class TC13564(_Overcommit):
    """Test overcommit logic in a 3 host pool NFS"""
    HOSTS = 3
    SF_STORAGE = "nfs"

class TC8009(_Overcommit):
    """Test overcommit logic in a 4 host pool"""
    HOSTS = 4
    
class TC13565(_Overcommit):
    """Test overcommit logic in a 4 host pool"""
    HOSTS = 4
    SF_STORAGE = "nfs"
    
class TC8010(_Overcommit):
    """Test overcommit logic in an 8 host pool"""
    HOSTS = 8

class TC8011(_Overcommit):
    """Test overcommit logic in a 16 host pool"""
    HOSTS = 16

class TC8191(_Overcommit):
    """Short test of overcommit logic in a 16 host pool"""
    HOSTS = 16
    OPS = 30 # 30 operations per nTol
    NTOLS = [1, 2, -1] # -1 = MAX
    EXISTING_POOL = True # We'll create the pool in prepare
    
class TC13566(TC8191):
    SF_STORAGE = "nfs"

class _XHA(_HATest):
    """Base class for xHA random operations tests"""
    HOSTS = 2
    OPCOUNT = 100
    # Set a sequence of operations in here to have them played back
    PLAYBACK = None
    EXISTING_HOSTS = False
    DURATION = 0 # Duration in minutes, 0 = use opcount...

    def __init__(self, tcid=None):
        self.ops = [ "blockHeartbeat",
                     "blockStatefile",
                     "killHost",
                     "newVM",
                     "delVM",
                     "restoreHost" ]
        self.guest = None
        self.guests = []
        self.hosts = {}
        self.nTol = 0
        self.hostMemory = 0
        self.minHosts = None
        self.startTime = None
        _HATest.__init__(self, tcid)

    def prepare(self, arglist=None):

        if self.DURATION > 0:
            self.startTime = xenrt.util.timenow()

        # Create a pool of n hosts, with HA enabled
        orderedhostlist = []
        for i in range(self.HOSTS):
            h = self.getHost("RESOURCE_HOST_%u" % (i))
            self.hostsToPowerOn.append(h)
            self.hosts[h] = True
            orderedhostlist.append(h)

        self.configureHAPool(orderedhostlist,
                             resetTFI=(not self.EXISTING_HOSTS))

        # Set nTol to 0 (don't want overcommit protection kicking in)
        self.pool.setPoolParam("ha-host-failures-to-tolerate", 0)

        # Block xapi startup
        for h in self.hosts.keys():
            h.execdom0("touch /etc/xensource/xapi_block_startup")

        # Create a template debian guest, and preCloneTailor it
        self.guest = self.pool.master.createGenericLinuxGuest(sr=self.guestSR.uuid)
        self.guest.preCloneTailor()
        self.guest.shutdown()

        # Set self.hostMemory to the memory available for VMs on each host (we
        # assume they are identical)
        self.hostMemory = int(self.hosts.keys()[1].getHostParam("memory-free")) / 1048576

        # Decide how many hosts to leave live, this is the minimum number that
        # will fit 3 VMs per host on
        wantedVMs = self.HOSTS * 3
        memRequired = self.guest.memory * wantedVMs
        self.minHosts = self.roundUpDivide(memRequired, self.hostMemory)

    def run(self, arglist=None):
        if self.PLAYBACK:
            opCount = len(self.PLAYBACK)
        else:
            opCount = self.OPCOUNT

        # Install 3 VMs per host...
        initialCount = self.HOSTS * 3
        xenrt.TEC().logverbose("Installing %u initial VMs" % (initialCount))
        hIndex = 0
        for i in range(initialCount):
            g = self.guest.cloneVM()
            g.host = self.hosts.keys()[hIndex]
            g.start()
            self.guests.append(g)
            g.setHAPriority(2)
            hIndex += 1
            if hIndex == self.HOSTS:
                hIndex = 0

        if self.DURATION == 0:
            # Do it on operation count
            for i in range(opCount):
                xenrt.TEC().logverbose("Operation %u/%u" % (i,opCount))
                self.doOp(i)
        else:
            # Do it on duration
            i = 0
            while ((xenrt.util.timenow() - self.startTime)/60) < self.DURATION:
                xenrt.TEC().logverbose("Operation %u" % (i))
                self.doOp(i)
                i += 1

    def doOp(self, i):
        if self.PLAYBACK:
            op = self.PLAYBACK[i]
        else:
            op = self.ops[random.randint(0, len(self.ops) - 1)]
        result = self.runSubcase(op, (), op, "%u_%s" % (i,op))
        if result != xenrt.RESULT_PASS and \
           result != xenrt.RESULT_SKIPPED:
            raise xenrt.XRTFailure("%u_%s failed" % (i,op))
        time.sleep(15)

    # Actual operations
    def blockHeartbeat(self):
        hosts = self.hosts.keys()
        random.shuffle(hosts)
        for h in hosts:
            # Is this a live host
            if self.hostLive(h,test=True):
                if h.haHeartbeatBlocks['allto'] or \
                   h.haHeartbeatBlocks['allfrom']:
                    # Heartbeat is blocked already
                    continue
                # Will blocking heartbeats kill it?
                expectToDie = False
                if not self.hostLive(h,test=True,heartbeatBlock=True):
                    # yes - check we can allow this
                    expectToDie = True
                    if not self.checkLive(h):
                        # We can't
                        continue
                # Do it
                xenrt.TEC().logverbose("blockHeartbeat - blocking %s" %
                                       (h.getName()))
                h.blockHeartbeat()
                if expectToDie:
                    if self.HOSTS == 2:
                        # 2 node pool, I will die if I'm not the lowest UUID
                        otherHost = None
                        for ho in self.pool.getHosts():
                            if ho != h:
                                otherHost = ho
                                break
                        if h.getMyHostUUID() < otherHost.getMyHostUUID():
                            self.pool.haLiveset.remove(otherHost.getMyHostUUID())
                        else:
                            self.pool.haLiveset.remove(h.getMyHostUUID())
                    else:
                        self.pool.haLiveset.remove(h.getMyHostUUID())
                self.afterCheck()
                return

        raise xenrt.XRTSkip("blockHeartbeat - No suitable host found")

    def blockStatefile(self):
        hosts = self.hosts.keys()
        random.shuffle(hosts)
        for h in hosts:
            # Is this a live host
            if self.hostLive(h,test=True):
                if h.haStatefileBlocked:
                    # Statefile is blocked already
                    continue
                # Will blocking statefile kill it?
                expectToDie = False
                if not self.hostLive(h,test=True,statefileBlock=True):
                    # yes - check we can allow this
                    expectToDie = True
                    if not self.checkLive(h):
                        # We can't
                        continue
                # Do it
                xenrt.TEC().logverbose("blockStatefile - blocking %s" %
                                       (h.getName()))
                h.blockStatefile()
                if expectToDie:
                    self.pool.haLiveset.remove(h.getMyHostUUID())
                self.afterCheck()
                return

        raise xenrt.XRTSkip("blockStatefile - No suitable host found")

    def killHost(self):
        hosts = self.hosts.keys()
        random.shuffle(hosts)
        for h in hosts:
            # Is this a live host
            if self.hostLive(h,test=True):
                if self.checkLive(h):
                    xenrt.TEC().logverbose("killHost - Powering off %s" %
                                           (h.getName()))
                    self.poweroff(h)
                    self.pool.haLiveset.remove(h.getMyHostUUID())
                    self.hosts[h] = False
                    if self.pool.master == h:
                        self.pool.findMaster()
                    self.afterCheck()
                    return
        raise xenrt.XRTSkip("killHost - No suitable host to kill found")

    def newVM(self):
        # Important: Check this shouldn't 'overcommit' us
        if ((len(self.guests) + 1) * self.guest.memory) > (self.hostMemory * self.minHosts):
            raise xenrt.XRTSkip("Adding another guest would overcommit us")        
        newHost = None
        for h in self.hosts.keys():
            if self.hostLive(h,test=False):
                if (int(h.getHostParam("memory-free")) / 1048576) > self.guest.memory:
                    newHost = h
                    break
        if not newHost:
            raise xenrt.XRTSkip("No hosts with enough memory left for guest")
        g = self.guest.cloneVM(name=xenrt.randomGuestName())
        xenrt.TEC().logverbose("newVM - Adding guest %s" % (g.getName()))
        g.host = newHost
        g.start()
        self.guests.append(g)
        g.setHAPriority(2)
        self.afterCheck()

    def delVM(self):
        if len(self.guests) == 0:
            # No guests, so skip
            raise xenrt.XRTSkip("No guests found, cannot remove")
        # Choose a random guest, shut it down and uninstall
        g = self.guests[random.randint(0, len(self.guests) - 1)]
        xenrt.TEC().logverbose("delVM - Removing guest %s" % (g.getName()))
        g.setHAPriority(protect=False)
        g.shutdown()
        g.uninstall()
        self.guests.remove(g)
        self.afterCheck()

    def restoreHost(self):
        hosts = self.hosts.keys()
        random.shuffle(hosts)
        for h in hosts:
            if not self.hostLive(h,test=True):
                # Restore this host
                if not self.hosts[h]:
                    # Need to boot it!
                    h.machine.powerctl.on()
                # Wait for SSH in case the previous op caused it to fence or
                # it's just rebooting now...
                h.waitForSSH(900)
                time.sleep(300)
                h.resetHeartbeatBlocks()
                h.haStatefileBlocked = False
                self.hosts[h] = True
                if not h.getMyHostUUID() in self.pool.haLiveset:
                    self.pool.haLiveset.append(h.getMyHostUUID())
                h.execdom0("rm -f /etc/xensource/xapi_block_startup || true")
                h.startXapi()
                h.execdom0("touch /etc/xensource/xapi_block_startup")
                self.afterCheck()
                return
        raise xenrt.XRTSkip("No hosts found to restore")

    # Utility functions
    def afterCheck(self):
        self.pool.sleepHA("W",multiply=3)

        if self.pool.master.getMyHostUUID() in self.pool.haLiveset:
            # Just in case
            self.pool.findMaster()
        else:
            # We expect it to have changed
            self.pool.findMaster(notCurrent=True, warnOnWait=True)

        self.pool.checkHA()
        for g in self.guests:
            g.findHost(timeout=900)
            g.check()

    def checkLive(self,host):
        # The proposed operation will leave host dead, ensure at least minHosts
        # other hosts are left live
        liveHosts = 0
        for h in host.pool.getHosts():
            if h != host:
                if self.hostLive(h, test=True):
                    liveHosts += 1
        return (liveHosts >= self.minHosts)

    def hostLive(self, host, test=False, heartbeatBlock=False,
                 statefileBlock=False):
        # Evaluate the survival rules for this host, and see if we expect it
        # to be live
        
        # Simple check, have we turned off the host?
        if not self.hosts[host]:
            if not test:
                xenrt.TEC().logverbose("Host %s explicitly powered off" %
                                       (host.getName()))
            return False

        # Survival Rule 1:
        # XAPI is running on the host, the host has access to the State-File and
        # knows it is a member of the largest partition, as determined through
        # communications on the State-File. Arbitrary partition tie-breaking
        # descisions may be necessary.

        # We assume xapi to be running (we don't explicitly stop it)
        if not host.haStatefileBlocked and not statefileBlock:
            # We only block all heartbeats
            if not host.haHeartbeatBlocks['allto'] and \
               not host.haHeartbeatBlocks['allfrom'] and \
                not heartbeatBlock:
                # Survival Rule 1 passed
                if not test:
                    xenrt.TEC().logverbose("Host %s passed survival rule 1" %
                                           (host.getName()))
                return True

        # Survival Rule 2:
        # XAPI is running on the host, the host has lost State-File access, and
        # knows ALL configured and non-excluded hosts are members of the
        # liveset, and that none of them have State-File access.

        # Again we assume xapi to be running
        # Check no hosts have statefile access, and that all have heartbeats
        ruleFailed = False
        for h in host.pool.getHosts():
            if h == host:
                if heartbeatBlock:
                    ruleFailed = True
            if h.haHeartbeatBlocks['allto'] or \
               h.haHeartbeatBlocks['allfrom']:
                ruleFailed = True
            if not h.haStatefileBlocked:
                ruleFailed = True
            if ruleFailed:
                break

        if not ruleFailed:
            # Survival Rule 2 passed
            if not test:
                xenrt.TEC().logverbose("Host %s passed survival rule 2" %
                                       (host.getName()))
            return True

        # No rules matched, so the host should be fenced...
        if not test:
            xenrt.TEC().logverbose("Host %s failed both survival rules" %
                                   (host.getName()))
        return False

    def roundUpDivide(self,a,b):
        # Return a/b rounded UP
        floated = float(a) / float(b)
        result = int(floated)
        remainder = floated - result
        if remainder > 0:
            result += 1
        return result

class TC8052(_XHA):
    """Test xHA in a 3 host pool"""
    HOSTS = 3

class TC8053(_XHA):
    """Test xHA in a 4 host pool"""
    HOSTS = 4

class TC8054(_XHA):
    """Test xHA in an 8 host pool"""
    HOSTS = 8

class TC8055(_XHA):
    """Test xHA in a 16 host pool"""
    HOSTS = 16
    DURATION = 1440 # 24 hours
    EXISTING_HOSTS = True

class TC8126(_XHA):
    """Regression test for CA-20814"""
    HOSTS = 4
    PLAYBACK = ["killHost", "delVM", "killHost", "killHost"]

class TC8043(_HATest):
    """VM Priority during failover"""

    def __init__(self, tcid=None):
        self.guest = None
        self.guests = []
        self.hosts = []
        self.hostMemory = 0
        self.guestsOnHost = 0
        _HATest.__init__(self, tcid)

    def prepare(self, arglist=None):
        for i in range(3):
            h = self.getHost("RESOURCE_HOST_%u" % (i))
            self.hostsToPowerOn.append(h)
            self.hosts.append(h)

        hostMem=[]
        for h in range(len(self.hosts)):
            m = int(self.hosts[h].getHostParam("memory-total"))
            hostMem.append(m)
            
        minMemHost=hostMem.index(min(hostMem))
        xenrt.TEC().logverbose(" MasterHost-%s"%(self.hosts[minMemHost]))
        
        #setting master with min memory  
        self.hosts[0],self.hosts[minMemHost]=self.hosts[minMemHost],self.hosts[0]

        self.configureHAPool(self.hosts)

        self.pool.setPoolParam("ha-host-failures-to-tolerate",1)

        # Create a template debian guest, and preCloneTailor it
        self.guest = self.pool.master.createGenericLinuxGuest(sr=self.guestSR.uuid)
        self.guest.preCloneTailor()
        self.guest.shutdown()
        # Use 512M to reduce the number of guests needed...
        self.guest.memset(512)
        
        # Set self.hostMemory to the memory available for VMs on each host (we
        # assume they are identical)
        if isinstance(self.hosts[0], xenrt.lib.xenserver.MNRHost):
            mem = self.hosts[0].maximumMemoryForVM(self.guest)
        else:
            mem = int(self.hosts[0].getHostParam("memory-free")) / xenrt.MEGA
        self.hostMemory = mem
        
        overhead = self.guest.computeOverhead()
        
        # Create enough guests to fill the first slave
        self.guestsOnHost = (self.hostMemory / (512+overhead))

        for i in range(self.guestsOnHost):
            g = self.guest.cloneVM()
            self.guests.append(g)
            g.host = self.pool.slaves.values()[0]
            g.start()
            g.setHAPriority(1)

        # Create two guests on the second slave (one high, one medium priority)
        for i in range(2):
            g = self.guest.cloneVM()
            self.guests.append(g)
            g.host = self.pool.slaves.values()[1]
            g.start()
            g.setHAPriority(i + 1)
            
    def run(self, arglist=None):
        # Power off both slaves
        for h in self.pool.slaves.values():
            self.poweroff(h)
            self.pool.haLiveset.remove(h.getMyHostUUID())
        
        # Give it 20 minutes to figure out the failures and restart VMs etc
        time.sleep(1200)

        # See what guests are up...
        upCounts = {1:0,2:0}
        for g in self.guests:
            g.host = self.pool.master
            if g.getState() == "UP":
                upCounts[int(g.getHAPriority())] += 1

        xenrt.TEC().logverbose("High priority guests up: %u, Medium priority "
                               "guests up: %u" % (upCounts[1],upCounts[2]))

        if (upCounts[1] + upCounts[2]) < self.guestsOnHost:
            raise xenrt.XRTError("Master has not been filled, still space for "
                                 "more guests")

        if upCounts[2] == 1 and upCounts[1] != (len(self.guests) - 1):
            raise xenrt.XRTFailure("Medium priority guest started ahead of "
                                   "high priority guest")
        elif upCounts[2] == 1:
            # This shouldn't happen, it means we were able to restart ALL guests
            # on the master...
            raise xenrt.XRTError("All guests were able to start")

class TC8078(_HATest):
    """HA message generation"""

    def __init__(self, tcid=None):
        _HATest.__init__(self, tcid=tcid)
        self.alerts = []
        self.alertParameters = ["name", "priority", "class", "obj-uuid",
                                "timestamp", "body"]
        self.guests = []

    def prepare(self, arglist=None):
        hosts = []
        for i in range(3):
            h = self.getHost("RESOURCE_HOST_%u" % (i))
            self.hostsToPowerOn.append(h)
            hosts.append(h)

        # Start with a pool of 3, with nTol set to 1
        self.configureHAPool(hosts)
        self.pool.setPoolParam("ha-host-failures-to-tolerate",1)

        # Create a template debian guest, and preCloneTailor it
        self.guest = self.pool.master.createGenericLinuxGuest(sr=self.guestSR.uuid)
        self.guest.preCloneTailor()
        self.guest.shutdown()
        self.guest.memset(1024)        

    def run(self, arglist=None):
        # subcases with nTol of 1
        subcases1 = ["blockStatefile", "blockHeartbeat", "blockAllStatefiles",
                     "blockXapiHealthchecker"]
        # subcases with nTol of 2
        subcases2 = ["powerOffSlave", "overCommit", "restartFail"]

        for s in subcases1:
            self.runSubcase(s, (), "haMessages", s)
            self.resetAlerts()

        self.pool.setPoolParam("ha-host-failures-to-tolerate", 2) 
        self.resetAlerts()

        for s in subcases2:
            self.runSubcase(s, (), "haMessages", s)
            self.resetAlerts()

    def blockStatefile(self):
        # 1. Block statefile on a slave, should generate an 
        # HA_STATEFILE_APPROACHING_TIMEOUT, followed by an HA_HOST_WAS_FENCED.
        slave = self.pool.slaves.values()[0]
        slave.blockStatefile()
        slave.skipNextCrashdump = True
        self.pool.sleepHA("W",multiply=3)
        self.checkForAlerts(["HA_HOST_FAILED"],
                            "Host",slave.getMyHostUUID())


    def blockHeartbeat(self):
        # 2. Block heartbeat on a slave, should generate an
        # HA_HEARTBEAT_APPROACHING_TIMEOUT, followed by an HA_HOST_WAS_FENCED.
        slave = self.pool.slaves.values()[0]
        slave.blockHeartbeat()
        time.sleep(600)
        self.checkForAlerts(["HA_HOST_WAS_FENCED"],
                            "Host",slave.getMyHostUUID())

    def blockAllStatefiles(self):
        # 3. Block statefile on all hosts, should generate HA_STATEFILE_LOST.
        self.pool.blockAllStatefiles()
        self.pool.sleepHA("W",multiply=3)
        self.checkForAlerts(["HA_STATEFILE_LOST"],"Host",
                            self.pool.master.getMyHostUUID())
        self.pool.blockAllStatefiles(block=False)
        self.pool.sleepHA("W",multiply=3)


    def blockXapiHealthchecker(self):
        # 4. Block the xapi healthchecker on a slave, should generate an
        # HA_XAPI_HEALTHCHECK_APPROACHING_TIMEOUT, followed by an 
        # HA_HOST_WAS_FENCED.
        slave = self.pool.slaves.values()[0]
        slave.execdom0("touch /tmp/fist_fail_healthcheck")
        slave.execdom0("touch /fist_fail_healthcheck || true")
        slave.execdom0("echo 'rm -f /tmp/fist_fail_healthcheck || true' >> "
                       "/etc/rc.d/rc.local")
        slave.execdom0("echo 'rm -f /fist_fail_healthcheck || true' >> "
                       "/etc/rc.d/rc.local")
        time.sleep(600)
        self.checkForAlerts(["HA_HOST_WAS_FENCED"],"Host",
                            slave.getMyHostUUID())

    def powerOffSlave(self):
        # 5. Power off a slave, should generate an HA_HOST_FAILED message, and a
        # HA_POOL_DROP_IN_PLAN_EXISTS_FOR, as we should now only have a plan as
        # to how to cope with 1 failure.
        slave = self.pool.slaves.values()[0]

        # We need to have at least 1 protected VM running at this point
        g = self.guest.cloneVM()
        g.host = self.pool.master
        g.start()
        g.setHAPriority(1)
        self.poweroff(slave)
        self.pool.sleepHA("W",multiply=3)
        self.checkForAlerts(["HA_HOST_FAILED"],"Host",slave.getMyHostUUID())
        self.checkForAlerts(["HA_POOL_DROP_IN_PLAN_EXISTS_FOR"],"Pool",
                            self.pool.getUUID())
        g.setHAPriority(protect=False)
        g.shutdown()
        g.uninstall()

        slave.machine.powerctl.on()
        time.sleep(300)

    def overCommit(self):
        # 6. Disable overcommit protection, and attempt to install more VMs than
        # fit on one host, should generate an HA_POOL_OVERCOMMITTED message.
        slave = self.pool.slaves.values()[0]
        self.pool.setPoolParam("ha-allow-overcommit", "true")
        self.guest.host = slave
        hostMemory = int(slave.getHostParam("memory-free")) / 1048576
        vmCount = hostMemory / 1024
        for i in range(vmCount+1):            
            g = self.guest.cloneVM()
            if i == vmCount:
                g.host = self.pool.master
            self.guests.append(g)
            g.start(specifyOn=False)
            g.setHAPriority(1)


        self.checkForAlerts(["HA_POOL_OVERCOMMITTED"],"Pool",
                            self.pool.getUUID())

        for g in self.guests:
            g.setHAPriority(protect=False)
            g.shutdown()
            g.uninstall()

    def restartFail(self):
        # 7. Take a protected VM running on NFS/ext storage. Power off the host 
        # it's on, and then delete it's VHD file. Should generate an 
        # HA_PROTECTED_VM_RESTART_FAILED message.
        slave = self.pool.slaves.values()[0]
        g = self.guest
        g.host = slave
        g.start()
        g.setHAPriority(1)
        # Get the VDI uuid of one of its disks
        vdis = self.pool.master.minimalList("vbd-list",
                                            "vdi-uuid",
                                            "vm-uuid=%s type=Disk" %
                                            (g.getUUID()))
        vdi = vdis[0]
        rc = self.pool.master.execdom0("ls /var/run/sr-mount/%s/%s.vhd" % 
                                       (self.guestSR.uuid,vdi),retval="code")
        if rc > 0:
            raise xenrt.XRTError("Cannot test for "
                                 "HA_PROTECTED_VM_RESTART_FAILED as can't find "
                                 "VDI to destroy")

        self.poweroff(slave)
        self.pool.master.execdom0("rm -f /var/run/sr-mount/%s/%s.vhd" %
                                  (self.guestSR.uuid,vdi))
        self.pool.sleepHA("W",multiply=3)
        self.checkForAlerts(["HA_PROTECTED_VM_RESTART_FAILED"],"VM",
                            g.getUUID())

    def getNewAlerts(self, alertNames=None):
        alerts = self.pool.master.minimalList("message-list")
        newAlerts = []
        retAlerts = []

        # Discard old alerts
        for a in alerts:
            if not a in self.alerts:
                newAlerts.append(a)

        # Get the details for the new ones
        for a in newAlerts:
            alertDetails = {'uuid':a}
            alertDetails['name'] = self.pool.master.parseListForOtherParam("message-list",
                                                                           "uuid",a,
                                                                           otherparam="name")
            if alertNames:
                # Is this an alert we care about?
                if not alertDetails['name'] in alertNames:
                    continue
            
                # Only need to get all the parameters if it's an alert we want,
                # otherwise just the UUID is sufficient
                for p in self.alertParameters:
                    param = self.pool.master.parseListForOtherParam("message-list",
                                                                    "uuid",a,
                                                                    otherparam=p)
                    alertDetails[p] = param

            retAlerts.append(alertDetails)

        return retAlerts

    def checkForAlerts(self, alerts, objClass, uuid):
        newAlerts = self.getNewAlerts(alertNames=alerts)
        alertsFound = []
        for na in newAlerts:
            xenrt.TEC().logverbose("Looking at alert %s" % (na))
            for a in alerts:
                if a in alertsFound:
                    continue
                if na['name'] == a and na['class'] == objClass and \
                   na['obj-uuid'] == uuid:
                    xenrt.TEC().logverbose("Found expected alert %s" % (na))
                    alertsFound.append(a)
                    break
        missingAlerts = []
        for a in alerts:
            if not a in alertsFound:
                missingAlerts.append(a)
        if len(missingAlerts) > 0:
            raise xenrt.XRTFailure("Could not find expected alert(s): %s" % 
                                   (missingAlerts))

    def resetAlerts(self):
        for a in self.getNewAlerts():
            self.alerts.append(a['uuid'])
        for h in self.pool.getHosts():
            h.machine.powerctl.on()
            h.waitForSSH(900)
            h.waitForXapi(300)
            h.waitForEnabled(300)

class TC8091(_HATest):
    """Verify pool-{join,eject} are blocked when HA is enabled"""

    def __init__(self, tcid=None):
        _HATest.__init__(self, tcid=tcid)
        self.host0 = None
        self.host1 = None
        self.host2 = None

    def prepare(self, arglist=None):

        self.host0 = self.getHost("RESOURCE_HOST_0")
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.host2 = self.getHost("RESOURCE_HOST_2")

        # Start with a pool of 2
        hosts = [self.host0, self.host1]
        self.configureHAPool(hosts)
        self.host2.resetToFreshInstall()

    def run(self, arglist=None):

        # Attempt to join a 3rd node to the pool, an HA_IS_ENABLED error should
        # be thrown and the operation blocked.
        joined = False
        try:
            self.pool.addHost(self.host2, force=True)
            joined = True
        except xenrt.XRTFailure, e:
            r = re.search(r"^Error code: (\S+)", e.data, re.MULTILINE)
            if r == None or r.group(1) != "HA_IS_ENABLED":
                xenrt.TEC().comment("Expected XRTFailure adding host but "
                                    "cannot find HA_IS_ENABLED: %s" % (e.data))
                self.setResult(xenrt.RESULT_PARTIAL)
            else:
                xenrt.TEC().comment("Expected HA_IS_ENABLED error when trying "
                                    "to add a host to an HA enabled pool")

        if joined:
            raise xenrt.XRTFailure("Allowed to add a host to an HA enabled pool")

        # Attempt to eject the slave from the pool, an HA_IS_ENABLED error 
        # should be thrown and the operation blocked.
        ejected = False
        try:
            self.pool.eject(self.host1)
            ejected = True
        except xenrt.XRTFailure, e:
            r = re.search(r"^Error code: (\S+)", e.data, re.MULTILINE)
            if r == None or r.group(1) != "HA_IS_ENABLED":
                xenrt.TEC().comment("Expected XRTFailure ejecting host but "
                                    "cannot find HA_IS_ENABLED: %s" % (e.data))
                self.setResult(xenrt.RESULT_PARTIAL)
            else:
                xenrt.TEC().comment("Expected HA_IS_ENABLED error when trying "
                                    "to eject a host from an HA enabled pool")

        if joined:
            raise xenrt.XRTFailure("Allowed to eject a host from an HA enabled "
                                   "pool")

class TC8097(_HATest):
    """Verify overcommit protection gets disabled if a bug prevents actual VM
       restarts"""

    def __init__(self, tcid=None):
        _HATest.__init__(self, tcid=tcid)
        self.guests = []

    def prepare(self, arglist=None):
        # Create a pool of 2 hosts, with HA enabled
        hosts = []
        for i in range(2):
            h = self.getHost("RESOURCE_HOST_%u" % (i))
            hosts.append(h)
            self.hostsToPowerOn.append(h)

        self.configureHAPool(hosts)
        self.pool.setPoolParam("ha-host-failures-to-tolerate", 1)

        # Set up 10 VMs
        # Create a template debian guest, and preCloneTailor it
        guest = self.pool.master.createGenericLinuxGuest(sr=self.guestSR.uuid)
        guest.preCloneTailor()
        guest.shutdown()

        for i in range(10):
            g = guest.cloneVM()
            self.guests.append(g)
            g.host = self.pool.slaves.values()[0]
            g.start()
            g.setHAPriority(1)

    def run(self, arglist=None):
        # Enable the FIST point by touching /fist_simulate_restart_failure
        self.pool.master.execdom0("touch /tmp/fist_simulate_restart_failure")
        self.pool.master.execdom0("touch /fist_simulate_restart_failure || true")
        # Power off the slave
        self.poweroff(self.pool.slaves.values()[0])
        # Ensure that eventually all protected VMs get restarted, and that
        # overcommit protection has been disabled
        time.sleep(600)
        if self.pool.getPoolParam("ha-overcommitted") != "true":
            raise xenrt.XRTFailure("CA-17770 Pool not "
                                   "overcommitted automatically")
        for g in self.guests:
            g.host = self.pool.master
            if g.getState() != "UP":
                raise xenrt.XRTFailure("CA-17770 Not all guests restarted")
            g.check()

    def postRun(self):
        if self.pool.master:
            try:
                self.pool.master.execdom0("rm -f /fist_simulate_restart_failure || true")
                self.pool.master.execdom0("rm -f /tmp/fist_simulate_restart_failure || true")
            except:
                xenrt.TEC().warning("Unable to remove fist file!")
        _HATest.postRun(self)

class TC8098(_HATest):
    """Verify that nTol cannot be set to a negative number"""

    def prepare(self, arglist=None):
        host = self.getHost("RESOURCE_HOST_0")
        self.configureHAPool([host])
        self.pool.setPoolParam("ha-host-failures-to-tolerate", 1)

    def run(self, arglist=None):
        try:
            self.pool.setPoolParam("ha-host-failures-to-tolerate", -1)
            raise xenrt.XRTFailure("CA-20612 Allowed to set nTol to -1")
        except xenrt.XRTFailure, e:
            r = re.search(r"^The value given is invalid", e.data, re.MULTILINE)
            if r == None:
                xenrt.TEC().comment("Expected XRTFailure exception with "
                                    "unexpected data when attempting to "
                                    "set nTol to -1: %s" % (e.data))
                self.setResult(xenrt.RESULT_PARTIAL)
            else:
                xenrt.TEC().comment("Expected invalid value exception when "
                                    "attempting to set nTol to -1")

        nTol = self.pool.getPoolParam("ha-host-failures-to-tolerate")
        if nTol != "1":
            raise xenrt.XRTFailure("CA-20612 After attempting to set nTol to "
                                   "-1, nTol changed from 1 to %s" % (nTol))

        self.pool.check()

# 'Stuck-state' recovery TCs

class _StuckState(_HATest):
    """Base class for 'stuck-state' recovery TCs"""
    SOFTWARE_TARGET = False

    def __init__(self, tcid=None):
        _HATest.__init__(self, tcid=tcid)
        self.master = None
        self.slave = None
        self.target = None

    def prepare(self, arglist=None):
        # Set up a 2-node pool with HA enabled
        host0 = self.getHost("RESOURCE_HOST_0")        
        host1 = self.getHost("RESOURCE_HOST_1")
        if self.SOFTWARE_TARGET and not self.SF_STORAGE.startswith("nfs"):
            host2 = self.getHost("RESOURCE_HOST_2")
            host2.resetToFreshInstall()
            self.target = host2.createGenericLinuxGuest()
            iqn = self.target.installLinuxISCSITarget()
            self.target.createISCSITargetLun(0, 1024)
            lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" % 
                                          (iqn, self.target.getIP()))
            self.configureHAPool([host0,host1],iscsiLun=lun)
        else:
            self.configureHAPool([host0,host1])
        self.pool.setPoolParam("ha-host-failures-to-tolerate", 1)
        self.master = self.pool.master
        self.slave = self.pool.slaves.values()[0]
        self.pool.syncDatabase() # Occasionally a host can reboot with no
                                 # network config, this is believed due to the
                                 # db not having synced

    def blockNFSOnBoot(self, host):
        host.execdom0("cp %s/remote/unblocknfs.sh /etc/unblocknfs.sh" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))
        if host.isCentOS7Dom0():
            host.execdom0("cp %s/remote/blocknfs_c7.sh /etc/init.d/blocknfs" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))
            host.execdom0("chmod a+x /etc/init.d/blocknfs")
            host.execdom0("chkconfig --add blocknfs")
        else:
            host.execdom0("cp %s/remote/blocknfsonboot.sh /etc/blocknfsonboot.sh" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))
            host.execdom0("chmod a+x /etc/blocknfsonboot.sh")
            host.execdom0("ln -s /etc/blocknfsonboot.sh /etc/rc3.d/S09blocknfs")

class TC8127(_StuckState):
    """Disable HA and Statefile delete with offline host"""

    def run(self, arglist=None):
        # 1. turn slave off
        self.hostsToPowerOn.append(self.slave)
        self.slave.shutdown()
        # Power off so the power on works correctly       
        self.slave.machine.powerctl.off()
        time.sleep(10)
        # 2. disable HA
        self.pool.disableHA(check=False)
        # 3. delete old statefile using the master
        vdis = self.master.minimalList("vdi-list", args="sr-uuid=%s" % 
                                                        (self.sr.uuid))
        for vdi in vdis:
            self.master.destroyVDI(vdi)
        # 4. turn on the slave
        self.slave.machine.powerctl.on()
        self.slave.waitForSSH(900)
        time.sleep(300)

        # The expected result is that the slave should come online, fail to
        # access the statefile but contact the old master and discover that HA
        # is disabled. The slave should then disarm itself and rejoin the Pool.
        self.pool.check()
        self.pool.checkHA()

class TC13522(TC8127):
    """Disable HA and Statefile delete with offline host for NFS SF"""
    SF_STORAGE = "nfs"
    
class TC26912(TC8127):
    """Disable HA and Statefile delete with offline host for NFSv4 SF"""
    SF_STORAGE = "nfs4"
  
class TC8128(_StuckState):
    """Disable HA with offline host"""

    def run(self, arglist=None):
        # 1. power off the slave
        self.hostsToPowerOn.append(self.slave)
        self.slave.shutdown()
        self.slave.machine.powerctl.off()
        time.sleep(10)
        # 2. disable HA via the master
        self.pool.disableHA(check=False)
        # 3. power on the slave
        self.slave.machine.powerctl.on()
        self.slave.waitForSSH(900)
        time.sleep(300)

        # The slave should come back, reattach the old statefile and discover
        # the pool state is now "invalid". The pool slave should disable HA
        # and rejoin the Pool.
        self.pool.check()
        self.pool.checkHA()

class TC8129(_StuckState):
    """Verify a booting host remains in emergency mode until it can see the HA
       statefile"""
    SOFTWARE_TARGET = True

    def run(self, arglist=None):
        # 1. power off slave
        self.hostsToPowerOn.append(self.slave)
        if self.SF_STORAGE.startswith("nfs"):
            self.blockNFSOnBoot(self.slave)
        self.slave.shutdown()
        self.slave.machine.powerctl.off()
        time.sleep(10)
        # 2. arrange to block statefile access on the slave when it returns
        if not self.SF_STORAGE.startswith("nfs"):            
            self.target.execguest("iptables -I INPUT -s %s -j DROP" % 
                                  (self.slave.getIP()))

        # 3. power on slave
        self.slave.machine.powerctl.on()
        self.slave.waitForSSH(900)
        time.sleep(300)
        # The slave should boot up and remain in emergency mode until the block
        # is removed
        data = self.slave.execdom0("xe vm-list || true")
        if not re.search("The host could not join the liveset", data):
            raise xenrt.XRTError("Slave not in HA emergency mode with statefile"
                                 " access blocked")
        # 4. remove the block
        if self.SF_STORAGE.startswith("nfs"):
            self.slave.execdom0("/etc/unblocknfs.sh")
        else:
            self.target.execguest("iptables -D INPUT -s %s -j DROP" %
                                  (self.slave.getIP()))

        time.sleep(120)
        data = self.slave.execdom0("xe vm-list || true")
        if re.search("The host could not join the liveset", data):
            raise xenrt.XRTFailure("Slave still in HA emergency mode 120s after "
                                   "statefile access restored")

        self.pool.haLiveset.append(self.slave.getMyHostUUID())

        self.pool.check()
        self.pool.checkHA()

class TC13523(TC8129):
    """Verify a booting host remains in emergency mode until it can see the HA
       statefile for NFS SF"""        
    SF_STORAGE = "nfs"
    
class TC26913(TC8129):
    """Verify a booting host remains in emergency mode until it can see the HA
       statefile for NFSv4 SF"""        
    SF_STORAGE = "nfs4"

class TC8130(_StuckState):
    """Verify that an HA-enabled pool can be recovered if all nodes reboot
       without statefile access"""
    SOFTWARE_TARGET = True

    def run(self, arglist=None):

        # 1. power off all nodes
        if self.SF_STORAGE.startswith("nfs"):
            for host in [self.slave, self.master]:
                self.blockNFSOnBoot(host)
        self.hostsToPowerOn.append(self.slave)
        self.hostsToPowerOn.append(self.master)
        self.poweroff(self.slave)
        self.poweroff(self.master)
        time.sleep(10)
        # 2. block access to the statefile globally (already done in the case of NFS)
        if self.SF_STORAGE != "nfs" and self.SF_STORAGE != "nfs4":
            self.target.shutdown()
        # 3. power on all nodes
        self.master.machine.powerctl.on()
        self.slave.machine.powerctl.on()
        self.master.waitForSSH(900)
        self.slave.waitForSSH(600)
        time.sleep(300)
        # At this point all nodes should be running in emergency mode:
        data = self.slave.execdom0("xe vm-list || true")
        if not re.search("The host could not join the liveset", data):
            raise xenrt.XRTError("Slave not in HA emergency mode with statefile"
                                 " access blocked")
        data = self.master.execdom0("xe vm-list || true")
        if not re.search("The host could not join the liveset", data):
            raise xenrt.XRTError("Master not in HA emergency mode with "
                                 "statefile access blocked")

        # 4. On the node which was the master perform xe host-emergency-ha-disable --force
        self.master.execdom0("xe host-emergency-ha-disable --force")

        # After a while both nodes should be up with HA disabled everywhere.
        time.sleep(300)

        self.pool.haEnabled = False
        self.pool.check()
        self.pool.checkHA()

class TC13524(TC8130):
    """Verify that an HA-enabled pool can be recovered if all nodes reboot
       without statefile access for NFS SF"""
    SF_STORAGE = "nfs"       

class TC26914(TC8130):
    """Verify that an HA-enabled pool can be recovered if all nodes reboot
       without statefile access for NFSv4 SF"""
    SF_STORAGE = "nfs4"

class TC8131(_StuckState):
    """Verify that an HA-enabled Pool can be recovered if only one slave reboots
       without statefile access"""
    SOFTWARE_TARGET = True

    def run(self, arglist=None):
        # 1. power off both hosts
        if self.SF_STORAGE.startswith("nfs"):
            for host in [self.slave, self.master]:
                self.blockNFSOnBoot(host)
        self.hostsToPowerOn.append(self.slave)
        self.hostsToPowerOn.append(self.master)
        self.poweroff(self.slave)
        self.poweroff(self.master)
        time.sleep(10)
        # 2. block access to the statefile globally (already done in the case of NFS)
        if self.SF_STORAGE != "nfs" and self.SF_STORAGE != "nfs4":
            self.target.shutdown()
        # 3. power on slave
        self.slave.machine.powerctl.on()
        self.slave.waitForSSH(900)
        time.sleep(300)
        # Observe that the slave comes up in emergency mode
        data = self.slave.execdom0("xe vm-list || true")
        if not re.search("The host could not join the liveset", data):
            raise xenrt.XRTError("Slave not in HA emergency mode with statefile"
                                 " access blocked")

        # 4. Force disable HA on the slave:
        self.slave.execdom0("xe host-emergency-ha-disable --force")

        # After a while HA should be disabled but the host will be in "ordinary"
        # emergency mode
        time.sleep(600)
        if xenrt.TEC().lookup("WORKAROUND_CA89303", False, boolean=True):
            xenrt.TEC().warning("Waiting an extra 10 minutes for host to become live (CA-89303)")
            time.sleep(600)

        if not self.slave.checkEmergency():
            okToIgnore = False
            if xenrt.TEC().lookup("WORKAROUND_CA89303", False, boolean=True):
                # The slave will still report it can't join the liveset, even though HA is disabled!
                data = self.slave.execdom0("xe vm-list || true")
                if re.search("The host could not join the liveset", data):
                    # Verify that attempting to disable HA reports it is already disabled
                    data = self.slave.execdom0("xe host-emergency-ha-disable --force || true")
                    if re.search("The operation could not be performed because HA is not enabled on the Pool", data):
                        # This is a slightly odd situation, but one we can accept
                        okToIgnore = True

            if not okToIgnore:                        
                raise xenrt.XRTFailure("Slave not in non-HA emergency mode after "
                                       "host-emergency-ha-disable command")

        # 5. Execute pool-emergency-transition-to-master
        self.slave.execdom0("xe pool-emergency-transition-to-master")
        time.sleep(60)

        # After a while the slave should be back as a pool of 1 with HA disabled
        self.pool.designateNewMaster(self.slave, metadataOnly=True)
        # We expect the original master to be offline...
        self.master.isOnline = False

        self.pool.haEnabled = False
        self.pool.check()
        self.pool.checkHA()

    def postRun(self):
        if self.master:
            self.master.isOnline = True
        _StuckState.postRun(self)

class TC13525(TC8131):
    """Verify that an HA-enabled Pool can be recovered if only one slave reboots
       without statefile access for NFS SF"""
    SF_STORAGE = "nfs"
    
class TC26915(TC8131):
    """Verify that an HA-enabled Pool can be recovered if only one slave reboots
       without statefile access for NFSv4 SF"""
    SF_STORAGE = "nfs4"
    
class TC8162(_HATest):
    """Verify host reboot and shutdown are blocked when relying on HA survival
       rule 2"""

    def run(self, arglist=None):
        # enable HA on one host
        host = self.getDefaultHost()
        self.hostsToPowerOn.append(host)
        pool = self.configureHAPool([host])

        # Disable the host
        host.disable()
        # Block statefile
        host.blockStatefile()
        # Wait to make sure this gets picked up
        pool.sleepHA("W", multiply=3)

        # CA-33676 Verify statefile access is blocked
        try:
            host.getHALiveSet()
        except:
            pass

        # Attempt xe host-shutdown and xe host-reboot, both should fail with
        # HA_LOST_STATEFILE
        cli = host.getCLIInstance()
        allowed = False
        try:
            cli.execute("host-evacuate", "uuid=%s" % (host.getMyHostUUID()))
            cli.execute("host-reboot", "uuid=%s" % (host.getMyHostUUID()))
            allowed = True
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Expected exception attempting to perform "
                                   "host-reboot")
            if not re.search("HA_LOST_STATEFILE", e.data):
                xenrt.TEC().warning("HA_LOST_STATEFILE not found in exception "
                                    "data")
        if allowed:
            raise xenrt.XRTFailure("CA-21745 Allowed to perform host-reboot on "
                                   "host using HA survival rule 2")

        allowed = False
        try:
            cli.execute("host-shutdown", "uuid=%s" % (host.getMyHostUUID()))
            allowed = True
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Expected exception attempting to perform "
                                   "host-shutdown")
            if not re.search("HA_LOST_STATEFILE", e.data):
                xenrt.TEC().warning("HA_LOST_STATEFILE not found in exception "
                                    "data")
        if allowed:
            raise xenrt.XRTFailure("CA-21745 Allowed to perform host-shutdown on "
                                   "host using HA survival rule 2")

class TC8188(xenrt.TestCase):
    """Verify HA survives when storage is on a different NIC to management"""

    def run(self, arglist=None):    

        # Get two hosts, reset to fresh install and configure networking
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")

        netConfig = """<NETWORK>
  <PHYSICAL network="NPRI">
    <NIC/>
    <MANAGEMENT/>
  </PHYSICAL>
  <PHYSICAL network="NSEC">
    <NIC/>
    <NIC/>
    <VLAN network="VU01">
      <STORAGE/>
    </VLAN>
  </PHYSICAL>
</NETWORK>"""

        # Set up networking on the target
        host1.createNetworkTopology(netConfig)

        # Set up a software iSCSI target on host1
        target = host1.createGenericLinuxGuest()
        iqn = target.installLinuxISCSITarget()
        # Switch it to be on VU01
        target.preCloneTailor() # Avoids any issues with mac address changes
        target.shutdown()
        target.removeVIF("eth0")
        nworks = host1.minimalList("network-list")
        vlanBridge = None
        for nw in nworks:
            if "VU01" in host1.genParamGet("network", nw, "name-label"):
                vlanBridge = host1.genParamGet("network", nw, "bridge")
                break
        target.createVIF("eth0", bridge=vlanBridge)
        target.start()
        target.createISCSITargetLun(0, 1024)


        # Make sure host0 can't see the target
        rc = host0.execdom0("ping -c 3 %s" % (target.getIP()), retval="code")
        if rc == 0:
            raise xenrt.XRTError("Host can see target before configuring VLAN")

        # Set up networking on host0
        host0.createNetworkTopology(netConfig)
        # Set up the SR on host0
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(host0, "TC8188")
        lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" %
                                      (iqn, target.getIP()))
        sr.create(lun, subtype="lvm", findSCSIID=True)

        # Enable ha
        pool = xenrt.lib.xenserver.poolFactory(host0.productVersion)(host0)
        pool.enableHA(srs=[sr.uuid])

        # Reboot the host
        host0.reboot()

        # Check the host is happy
        host0.check()
        pool.check()

class TC8232(_HATest):
    """Regression test for CA-22780"""

    def run(self, arglist=None):
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")

        pool = self.configureHAPool([host0,host1])
        m = pool.master

        g = m.createGenericLinuxGuest(sr=self.guestSR.uuid)
        # Put in a CD to make sure we get the VBD created
        g.changeCD("w2k3eesp2.iso")
        time.sleep(30)
        g.changeCD(None)
        g.setHAPriority(2)

        # Try and connect the local CD drive
        sr = m.minimalList("sr-list", args="content-type=iso type=udev "
                                           "host=%s" % (m.getName()))[0]
        vdis = m.minimalList("vdi-list", args="sr-uuid=%s" % (sr))
        if len(vdis) == 0:
            raise xenrt.XRTError("Host %s does not have a physical CD drive" %
                                 (m.getName()))
        vdi = vdis[0]
        # Find the VBD UUID
        vbd = m.minimalList("vm-cd-list", args="uuid=%s" % (g.getUUID()))[0]
        cli = m.getCLIInstance()

        # Try and insert it
        allowed = False
        try:
            cli.execute("vbd-insert", "uuid=%s vdi-uuid=%s" % (vbd,vdi))
            allowed = True
        except:
            pass

        if allowed:
            raise xenrt.XRTFailure("CA-22780 Allowed to insert physical CD "
                                   "drive VDI to HA protected VM")

class TC8427(_HATest):
    """Verify the Pool.ha_prevent_restarts_for field works as expected"""

    def run(self, arglist=None):
        # Set up a pool of two hosts
        host0 = self.getHost("RESOURCE_HOST_0")
        self.host0 = host0
        host1 = self.getHost("RESOURCE_HOST_1")
        pool = self.configureHAPool([host0,host1])
        self.pool = pool

        # Set up one protected VM per host
        guest0 = host0.createGenericLinuxGuest(sr=self.guestSR.uuid)
        guest0.setHAPriority(2)
        guest1 = host1.createGenericLinuxGuest(sr=self.guestSR.uuid)
        guest1.setHAPriority(2)

        # Verify basic functionality
        # ==========================
        cli = pool.getCLIInstance()
        cli.execute("pool-ha-prevent-restarts-for", "seconds=120")
        # Turn off the slave, and wait 60 seconds
        self.hostsToPowerOn.append(host1)
        self.poweroff(host1)
        time.sleep(60)
        # Verify slave is still marked as live, and VM apparently running
        if host1.getHostParam("host-metrics-live") != "true":
            raise xenrt.XRTFailure("Powered off slave marked as dead before "
                                   "ha_prevents_restarts_for timer expired")
        if guest1.getState() != "UP":
            raise xenrt.XRTFailure("Guest on powered off slave marked as dead "
                                   "before ha_prevents_restarts_for timer "
                                   "expired")
        # Check guest hasn't been restarted
        if guest1.paramGet("resident-on") != host1.getMyHostUUID():
            raise xenrt.XRTFailure("Guest on powered off slave has been "
                                   "restarted before ha_prevents_restarts_for "
                                   "timer has expired")

        # Wait for 1.5 minutes more
        time.sleep(90)
        # Verify slave is marked as dead, and VM is running
        if host1.getHostParam("host-metrics-live") != "false":
            raise xenrt.XRTFailure("Powered off slave marked as alive after "
                                   "ha_prevents_restarts_for timer expired")
        h = guest1.findHost()
        if h == host1:
            raise xenrt.XRTFailure("Guest not restarted after "
                                   "ha_prevents_restarts_for timer expired")

        # Reset the configuration
        host1.machine.powerctl.on()
        host1.waitForSSH(900)
        # Give it 3 mins to become enabled etc
        time.sleep(300)
        guest1.migrateVM(host1)
        cli.execute("pool-ha-prevent-restarts-for", "seconds=0")

        # Verify that changing timer once its running is honoured
        # =======================================================
        cli.execute("pool-ha-prevent-restarts-for", "seconds=1200")
        self.poweroff(host1)
        time.sleep(120)
        # Verify slave is still marked as live, and VM apparently running
        if host1.getHostParam("host-metrics-live") != "true":
            raise xenrt.XRTFailure("Powered off slave marked as dead before "
                                   "ha_prevents_restarts_for timer expired")
        if guest1.getState() != "UP":
            raise xenrt.XRTFailure("Guest on powered off slave marked as dead "
                                   "before ha_prevents_restarts_for timer "
                                   "expired")
        # Check guest hasn't been restarted
        if guest1.paramGet("resident-on") != host1.getMyHostUUID():
            raise xenrt.XRTFailure("Guest on powered off slave has been "
                                   "restarted before ha_prevents_restarts_for "
                                   "timer has expired")
        cli.execute("pool-ha-prevent-restarts-for", "seconds=0")
        time.sleep(30)
        # Verify slave is marked as dead, and VM is running
        if host1.getHostParam("host-metrics-live") != "false":
            raise xenrt.XRTFailure("Powered off slave marked as alive after "
                                   "ha_prevents_restarts_for timer expired")
        h = guest1.findHost()
        if h == host1:
            raise xenrt.XRTFailure("Guest not restarted after "
                                   "ha_prevents_restarts_for timer expired")

        # Reset the configuration
        host1.machine.powerctl.on()
        host1.waitForSSH(900)
        time.sleep(300)
        guest1.migrateVM(host1)
        cli.execute("pool-ha-prevent-restarts-for", "seconds=0")

        # Verify that the command blocks if tasks are in progress
        # =======================================================
        host0.execdom0("touch /tmp/fist_simulate_blocking_planner")
        time.sleep(40)
        host0.execdom0("(sleep 30 && rm -f /tmp/fist_simulate_blocking_planner)"
                       " > /dev/null 2>&1 < /dev/null &")
        st = xenrt.util.timenow()
        cli.execute("pool-ha-prevent-restarts-for", "seconds=1")
        timeTaken = xenrt.util.timenow() - st
        if timeTaken < 25 or timeTaken > 35:
            raise xenrt.XRTFailure("Command blocked with simulated in progress "
                                   "task for unexpected amount of time",
                                   data="Expecting ~30s, actual %ds" % (timeTaken))

    def postRun(self):
        try:
            if self.host0:
                self.host0.execdom0("rm -f /tmp/fist_simulate_blocking_planner "
                                    "|| true")
        except:
            pass
        try:
            if self.pool:
                cli = self.pool.getCLIInstance()
                cli.execute("pool-ha-prevent-restarts-for", "seconds=0")
        except:
            pass

class TC8466(xenrt.TestCase):
    """HA cannot be enabled if any master PIFs are unplugged which have disallow-unplug=true"""

    MASTER = True
    SLAVES = False

    def prepare(self, arglist=None):
        self.sr = None
        self.lun = None
        self.pool = self.getDefaultPool()
        self.pifs = []
        cli = self.pool.getCLIInstance()

        # Make sure the network topology is correct
        for h in self.pool.getHosts():
            # Each host should have at least one non-management PIF that
            # has disallow-unplug set
            pifs = h.minimalList(\
                "pif-list",
                "uuid",
                "host-uuid=%s management=false disallow-unplug=true" %
                (h.getMyHostUUID()))
            for pif in pifs:
                if not h.genParamGet("pif", pif, "IP-configuration-mode") in \
                       ("DHCP", "Static"):
                    pifs.remove(pif)
            if len(pifs) == 0:
                raise xenrt.XRTError("No suitable storage PIF found on host",
                                     h.getName())

            if (self.MASTER and h is self.pool.master) or \
                   (self.SLAVES and not h is self.pool.master):
                # This host needs a PIF unplugged
                pif = pifs[0]
            
                # Now unplug this PIF
                try:
                    h.genParamSet("pif", pif, "disallow-unplug", "false")
                    cli.execute("pif-unplug", "uuid=%s" % (pif))
                finally:
                    h.genParamSet("pif", pif, "disallow-unplug", "true")

                # Check
                if h.genParamGet("pif", pif, "currently-attached") != "false":
                    raise xenrt.XRTError("PIF not unplugged before test",
                                         pif)

                self.pifs.append(pif)
            else:
                # This host needs the PIF(s) plugged
                for pif in pifs:
                    if h.genParamGet("pif", pif, "currently-attached") \
                           != "true":
                        cli.execute("pif-plug", "uuid=%s" % (pif))

        if len(self.pifs) == 0:
            raise xenrt.XRTError("No suitable PIFs found for unplugging")
        
        # Set up the iSCSI HA SR
        self.lun = xenrt.ISCSITemporaryLun(300)
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(\
            self.pool.master, "TC-8466")
        self.sr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True)

    def run(self, arglist=None):

        # Attempt to enable HA. It should fail
        try:
            self.pool.enableHA(check=False)
        except xenrt.XRTFailure, e:
            if re.search(r"REQUIRED_PIF_IS_UNPLUGGED", e.data):
                # As expected
                pass
            else:
                raise e
        else:
            raise xenrt.XRTFailure("HA was enabled with a storage PIF unplugged")
        
    def postRun(self):
        # Disable HA
        try:
            self.pool.disableHA(check=False)
        except:
            pass

        # Put the PIF back to how they were
        cli = self.pool.getCLIInstance()
        for pif in self.pifs:
            try:
                cli.execute("pif-plug", "uuid=%s" % (pif))
            except:
                pass
        
        # Remove the SR
        if self.sr:
            try:
                self.sr.remove()
            except:
                pass

        if self.lun:
            self.lun.release()

class TC8540(TC8466):
    """HA cannot be enabled if any slave PIFs are unplugged which have disallow-unplug=true"""

    MASTER = False
    SLAVES = True

class TC8468(xenrt.TestCase):
    """Xapi should not replug attached PIFs on startup"""

    def prepare(self, arglist=None):
        self.sr = None
        self.lun = None
        self.pool = self.getDefaultPool()
        self.lcModified = None

        # Set up the iSCSI HA SR
        self.lun = xenrt.ISCSITemporaryLun(300)
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(\
            self.pool.master, "TC-8468")
        self.sr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True)

        # Enable HA
        self.pool.enableHA(check=False)
        time.sleep(60)

    def run(self, arglist=None):
        try:
            self.pool.master.getInventoryItem("CURRENT_INTERFACES")
            invitem = "CURRENT_INTERFACES"
        except:
            invitem = "HA_INTERFACES"

        # Get the list of interfaces used by HA
        text = self.pool.master.getInventoryItem(invitem)
        if not text:
            raise xenrt.XRTError("Could not find %s in inventory" % (invitem))
        haintfs = text.split()
        if len(haintfs) == 0:
            raise xenrt.XRTError("No HA interfaces listed in %s" % (invitem))

        # Restart API
        if isinstance(self.pool.master, xenrt.lib.xenserver.host.BostonHost):
            logmarker = self.pool.master.execdom0(\
                "tail -n1 /var/log/messages").strip()
        else: 
            logmarker = self.pool.master.execdom0(\
                "tail -n1 /var/log/xensource.log").strip()
        self.pool.master.restartToolstack()
        time.sleep(60)
        
        # Check the logs for the HA interfaces not being replugged
        
        if isinstance(self.pool.master, xenrt.lib.xenserver.BostonHost):
            data = self.pool.master.execdom0(\
                "grep -e 'interface-reconfigure' -e '%s' "
                "/var/log/messages.1 /var/log/messages | cat" %
                (logmarker.replace("'", ".").replace("[", ".").replace("]", ".")))
            data = data.split(logmarker)[-1]
            r = re.findall("interface-reconfigure", data)
            if len(r) == 0:
                raise xenrt.XRTFailure(\
                    "Found no log messages for PIF non-replugging")
        else:
            data = self.pool.master.execdom0(\
                "grep -e 'Marking PIF device' -e '%s' "
                "/var/log/xensource.log.1 /var/log/xensource.log | cat" %
                (logmarker.replace("'", ".").replace("[", ".").replace("]", ".")))
            data = data.split(logmarker)[-1]
            r = re.findall("Marking PIF device (\S+) as attached", data)
            if len(r) == 0:
                raise xenrt.XRTFailure(\
                    "Found no log messages for PIF non-replugging")
            for haintf in haintfs:
                ethintf = haintf.replace("xenbr", "eth")
                if not haintf in r and not ethintf in r:
                    raise xenrt.XRTFailure(\
                        "No PIF non-replug log message for a HA interface",
                        haintf)
        
    def postRun(self):
        # Disable HA
        try:
            self.pool.disableHA(check=False)
        except:
            pass

        # Remove the SR
        if self.sr:
            try:
                self.sr.remove()
            except:
                pass

        if self.lun:
            self.lun.release()

        if self.lcModified:
            # Copy back the original log config and restart
            h = self.lcModified
            h.execdom0("cp -f /etc/xensource/log.conf.xenrt "
                       "/etc/xensource.log.conf")
            h.restartToolstack()
            h.execdom0("rm -f /var/log/xensource.log")

class TC8469(xenrt.TestCase):
    """Warnings for storage PIFs not having disallow-unplug=true on HA enable"""

    # [20090112 15:49:36.108| warn|cl07-01|1516 inet-RPC|pool.enable_ha R:d794a2cef268|xapi_ha] Warning: A possible network anomaly was found. The following hosts possibly have storage PIFs that can be unplugged: A possible network anomaly was found. The following hosts possibly have storage PIFs that are not dedicated:, cl07-01: eth1 (uuid: b63dc5d8-c4f7-ae91-5242-4f5f51f42131)

    def prepare(self, arglist=None):
        self.sr = None
        self.lun = None
        self.pool = self.getDefaultPool()
        self.lcModified = None

        self.pifs = []
        cli = self.pool.getCLIInstance()

        # Find a storage PIF on each host
        for h in self.pool.getHosts():
            pifs = h.minimalList(\
                "pif-list",
                "uuid",
                "host-uuid=%s management=false disallow-unplug=true" %
                (h.getMyHostUUID()))
            for pif in pifs:
                if not h.genParamGet("pif", pif, "IP-configuration-mode") in \
                       ("DHCP", "Static"):
                    pifs.remove(pif)
            if len(pifs) == 0:
                raise xenrt.XRTError("No suitable storage PIF found on host",
                                     h.getName())
            pif = pifs[0]
            self.pifs.append(pif)

            # Make sure the PIF is plugged
            if h.genParamGet("pif", pif, "currently-attached") != "true":
                cli.execute("pif-plug", "uuid=%s" % (pif))

            # Remove disallow-unplug=true
            h.genParamSet("pif", pif, "disallow-unplug", "false")

        # Set up the iSCSI HA SR
        self.lun = xenrt.ISCSITemporaryLun(300)
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(\
            self.pool.master, "TC-8469")
        self.sr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True)

    def run(self, arglist=None):

        # Enable HA
        logmarker = self.pool.master.execdom0(\
            "tail -n1 /var/log/xensource.log").strip()
        self.pool.enableHA(check=False)
        time.sleep(60)

        # Check for warnings
        data = self.pool.master.execdom0(\
            "grep -e 'The following hosts possibly have storage PIFs' -e '%s' "
            "/var/log/xensource.log.1 /var/log/xensource.log | cat" %
            (logmarker.replace("'", ".").replace("[", ".").replace("]", ".")))
        data = data.split(logmarker)[-1]
        if not re.search("The following hosts possibly have storage PIFs "
                         "that can be unplugged", data):
            raise xenrt.XRTFailure("Found no warnings about disallow-unplug")
        for pif in self.pifs:
            if not re.search(pif, data):
                raise xenrt.XRTFailure(\
                    "Storage PIF without disallow-unplug=true not found in "
                    "warnings",
                    pif)

    def postRun(self):
        # Disable HA
        try:
            self.pool.disableHA(check=False)
        except:
            pass

        # Put the PIF back to how they were
        for pif in self.pifs:
            try:
                self.pool.master.genParamSet("pif",
                                             pif,
                                             "disallow-unplug",
                                             "true")
            except:
                pass
        
        # Remove the SR
        if self.sr:
            try:
                self.sr.remove()
            except:
                pass

        if self.lun:
            self.lun.release()

        if self.lcModified:
            # Copy back the original log config and restart
            h = self.lcModified
            h.execdom0("cp -f /etc/xensource/log.conf.xenrt "
                       "/etc/xensource.log.conf")
            h.restartToolstack()
            h.execdom0("rm -f /var/log/xensource.log")

class TC8757(_HATest):
    """Check the pool-pre-ha-vm-restart hook is called correctly"""

    def prepare(self, arglist=None):
        # Create an HA enabled pool of 3 hosts
        host0 = self.getHost("RESOURCE_HOST_0")
        host1 = self.getHost("RESOURCE_HOST_1")
        host2 = self.getHost("RESOURCE_HOST_2")
        pool = self.configureHAPool([host0,host1,host2])
        self.pool = pool

        # Assume the pool default SR is a shared one, and is appropriate for HA
        sruuid = self.guestSR.uuid
        self.sr = sruuid

        # Install a VM
        self.guest1 = self.pool.master.createGenericLinuxGuest(sr=sruuid)
        self.guestsToUninstallBeforeSRDestroy.append(self.guest1)
        # Clone it to create 3 others
        self.guest1.preCloneTailor()
        self.guest1.shutdown()
        slaves = self.pool.getSlaves()
        self.guest2 = self.guest1.cloneVM()
        self.guestsToUninstallBeforeSRDestroy.append(self.guest2)
        self.guest2.host = slaves[0]
        self.host2 = slaves[0]
        self.guest3 = self.guest1.cloneVM()
        self.guestsToUninstallBeforeSRDestroy.append(self.guest3)
        self.guest3.host = slaves[1]
        self.host3 = slaves[1]
        self.guest4 = self.guest1.cloneVM()
        self.guestsToUninstallBeforeSRDestroy.append(self.guest4)
        self.guest1.start()
        self.guest2.start()
        self.guest3.start()
        self.guest4.start()
        self.guest4.shutdown()

        # Protect the first 3 VMs
        self.guest1.setHAPriority(1)
        self.guest2.setHAPriority(1)
        self.guest3.setHAPriority(1)

        # Set up the hook script
        hookScript = """#!/bin/sh

logger pool-pre-ha-vm-restart about to start a level 2 VM
pool=$(xe pool-list params=uuid --minimal)
ha=$(xe pool-param-get uuid=$pool param-name=ha-allow-overcommit)
xe pool-param-set uuid=$pool ha-allow-overcommit=true

xe vm-start uuid=%s

xe pool-param-set uuid=$pool ha-allow-overcommit=$ha

exit 0
""" % (self.guest4.getUUID())
        fName = xenrt.TEC().tempFile()
        f = file(fName,"w")
        f.write(hookScript)
        f.close()
        # Copy the hook script to the master
        self.pool.master.execdom0("mkdir -p /etc/xapi.d/pool-pre-ha-vm-restart")
        sftp = self.pool.master.sftpClient()
        try:
            sftp.copyTo(fName,
                        "/etc/xapi.d/pool-pre-ha-vm-restart/20-dosomethingbad")
        finally:
            sftp.close()

    def run(self, arglist=None):
        # Power off host 3, causing VM 3 to fail
        self.host3.poweroff()
        self.pool.haLiveset.remove(self.host3.getMyHostUUID())
        # VMs 3+4 should started (4 first)
        if not self.guest4.findHost():
            raise xenrt.XRTFailure("VM 4 did not start within timeout")
        if not self.guest3.findHost():
            raise xenrt.XRTFailure("VM 3 did not start within timeout")

        # Power off VM4, and wait 60s to verify it remains off
        self.guest4.shutdown()
        time.sleep(60)
        if self.guest4.getState() != "DOWN":
            raise xenrt.XRTFailure("VM 4 did not remain shutdown")

        # Power off host 2, causing VM2 to fail (and potentially VM3, but we
        # don't care)
        self.host2.poweroff()
        self.pool.haLiveset.remove(self.host2.getMyHostUUID())
        # VMs 2+4 should start (4 first)
        if not self.guest4.findHost():
            raise xenrt.XRTFailure("VM 4 did not start within timeout")
        if not self.guest2.findHost():
            raise xenrt.XRTFailure("VM 2 did not start within timeout")

        self.guest4.shutdown()

        # Power on hosts 3 and 3
        self.host2.machine.powerctl.on()
        self.host3.machine.powerctl.on()
        self.host2.waitForSSH(900, desc="Host boot after power on")
        self.host3.waitForSSH(900, desc="Host boot after power on")
        self.host2.waitForEnabled(300)
        self.host3.waitForEnabled(300)
        self.pool.haLiveset.append(self.host2.getMyHostUUID())
        self.pool.haLiveset.append(self.host3.getMyHostUUID())

        # Migrate VM 3 to host 3
        self.guest3.findHost()
        self.guest3.migrateVM(self.host3)
        # Make VM 3 'best-effort'
        self.guest3.setHAPriority(protect=True, restart=False)
        
        # Power off host 3
        self.host3.poweroff()
        self.pool.haLiveset.remove(self.host3.getMyHostUUID())

        # VMs 3+4 should start (4 first)
        if not self.guest4.findHost():
            raise xenrt.XRTFailure("VM 4 did not start within timeout")
        if not self.guest3.findHost():
            raise xenrt.XRTFailure("VM 3 did not start within timeout")

        self.guest4.shutdown()

        # Install a new VM
        self.guest5 = self.pool.master.createGenericLinuxGuest(sr=self.sr)
        self.guestsToUninstallBeforeSRDestroy.append(self.guest5)
        self.guest5.setHAPriority(1)
        # Get the domid
        g5domid = self.guest5.getDomid()
        # Shut down the VM - HA should reboot it and at the same time start guest4
        self.guest5.execguest("/sbin/poweroff")
        time.sleep(300)

        # Check that both 4 and 5 have started
        if not self.guest4.findHost():
            raise xenrt.XRTFailure("VM 4 did not start within timeout")
        if not self.guest5.findHost():
            raise xenrt.XRTFailure("VM 5 did not start within timeout")
        if self.guest5.getDomid() == g5domid:
            raise xenrt.XRTFailure("VM 5 did not reboot as expected")

    def postRun(self):
        # Disable HA, and remove hook script
        if self.pool:
            if self.pool.haEnabled:
                self.pool.disableHA()
            self.pool.master.execdom0("rm -fr /etc/xapi.d/pool-pre-ha-vm-restart || true")

class TC10754(xenrt.TestCase):
    """Check METADATA_LUN_{BROKEN,HEALTHY} alerts are not generated by default"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.pool = xenrt.lib.xenserver.poolFactory(self.host.productVersion)(self.host)
        self.lun = xenrt.ISCSITemporaryLun(300)
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(\
            self.host, "TC-10754")
        self.sr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True, multipathing=False)

        self.pool.enableHA()

        # Start a script that writes to the xapi database every 10 seconds
        script = """#!/bin/bash
i=0
pool=`xe pool-list --minimal`
while [ 1 ]; do
  xe pool-param-set uuid=${pool} other-config:xenrtcount=$i
  i=$((i + 1))
  sleep 10
done
"""
        tf = xenrt.TEC().tempFile()
        f = file(tf,"w")
        f.write(script)
        f.close()
        sftp = self.host.sftpClient()
        sftp.copyTo(tf, "/root/TC10754.sh")
        sftp.close()
        self.host.execdom0("chmod +x /root/TC10754.sh")
        self.host.execdom0("/root/TC10754.sh >/dev/null 2>&1 < /dev/null &")

    def run(self, arglist=None):
        # Block iscsi access to the statefile, wait 6 minutes, unblock, wait 6 minutes.
        # Verify we have no extra alerts afterwards
        startAlerts = self.host.minimalList("message-list")
        self.host.execdom0("iptables -I OUTPUT -p tcp --dport 3260 -j DROP")
        self.host.execdom0("iptables -nL OUTPUT")
        time.sleep(360)
        self.host.execdom0("iptables -nL OUTPUT")
        self.host.execdom0("iptables -D OUTPUT -p tcp --dport 3260 -j DROP")
        time.sleep(360)

        endAlerts = self.host.minimalList("message-list")
        # Only extra alert we should have is 'HA_STATEFILE_LOST'
        foundMD = False
        unknown = False
        for e in endAlerts:
            if not e in startAlerts:
                n = self.host.genParamGet("message", e, "name")
                if re.match("METADATA_LUN_(BROKEN|HEALTHY)", n):
                    foundMD = True
                    break
                elif n in ["HA_STATEFILE_LOST", "MULTIPATH_PERIODIC_ALERT"]:
                    continue
                else:
                    unknown = True
        if foundMD:
            raise xenrt.XRTFailure("METADATA_LUN_* alert found when not expected")
        elif unknown:
            raise xenrt.XRTError("Unknown extra alert(s) found")

        # Now enable the other-config key and repeat
        self.pool.setPoolParam("other-config:metadata_lun_alerts", "true")
        self.host.execdom0("iptables -I OUTPUT -p tcp --dport 3260 -j DROP")
        time.sleep(360)
        self.host.execdom0("iptables -D OUTPUT -p tcp --dport 3260 -j DROP")
        time.sleep(360)

        finalAlerts = self.host.minimalList("message-list")

        foundBroken = False
        foundHealthy = False
        foundUnknown = False
        for e in finalAlerts:
            if not e in endAlerts:
                n = self.host.genParamGet("message", e, "name")
                if n == "METADATA_LUN_BROKEN":
                    foundBroken = True
                elif n == "METADATA_LUN_HEALTHY":
                    foundHealthy = True
                elif not n in ["HA_STATEFILE_LOST", "MULTIPATH_PERIODIC_ALERT"]:
                    foundUnknown = True

        if not foundBroken:
            raise xenrt.XRTFailure("Didn't find METADATA_LUN_BROKEN alert")
        if not foundHealthy:
            raise xenrt.XRTFailure("Didn't find METADATA_LUN_HEALTHY alert")
        if foundUnknown:
            raise xenrt.XRTError("Unknown extra alert(s) found")

    def postRun(self):
        if self.host:
            try:
                self.host.removeHostParam("other-config", "metadata_lun_alerts")
            except:
                pass
            try:
                self.host.execdom0("iptables -D OUTPUT -p tcp --dport 3260 -j DROP")
            except:
                pass
            try:
                self.host.execdom0("killall -9 TC10754.sh")
            except:
                pass
        if self.pool:
            try:
                self.pool.disableHA()
            except:
                pass
        if self.sr:
            try:
                self.sr.remove()
            except:
                pass
        if self.lun:
            self.lun.release()



class TC11845(xenrt.TestCase):

    
    def installVMs(self):
        
        cvsm_host = self.cvsm_vm.getHost()
        free_hosts = set(self.hosts) - set([cvsm_host, self.pool.master])

        self.hosts_1 = set()
        self.hosts_1.add(list(free_hosts)[0])
        self.hosts_1.add(cvsm_host)
        self.hosts_2 = list(set(self.hosts) - self.hosts_1)
        self.hosts_1 = list(self.hosts_1)

        self.guests = list()
        
        xenrt.TEC().logverbose("CVSMSERVER host is %s" % cvsm_host.getName())
        xenrt.TEC().logverbose("Pool master is %s" % self.pool.master.getName())
        xenrt.TEC().logverbose("hosts chosen for initial install of VMs are %s and %s" % 
                               (self.hosts_1[0].getName(),self.hosts_1[1].getName()))
        xenrt.TEC().logverbose("empty hosts at the moment are %s and %s" %
                               (self.hosts_2[0].getName(),self.hosts_2[1].getName()))
        # for the first machine
        host = self.hosts_1[0]
        xenrt.TEC().logverbose("installing VMs on %s" % host.getName())
        if cvsm_host is host:
            no_of_vms_on_host_1 = 4
            no_of_vms_on_host_2 = 5
        else:
            no_of_vms_on_host_1 = 5
            no_of_vms_on_host_2 = 4
            
        for i in range(no_of_vms_on_host_1):
            g = host.createGenericLinuxGuest(sr=self.cvsmsr.uuid)
            self.guests.append(g)
            
        # for the second machine
        host = self.hosts_1[1]
        xenrt.TEC().logverbose("installing VMs on %s" % host.getName())
        for i in range(no_of_vms_on_host_2):
            g = host.createGenericLinuxGuest(sr=self.cvsmsr.uuid)
            self.guests.append(g)

        for g in self.guests:
            g.setHAPriority(1)
            
        self.cvsm_vm.setHAPriority(1)


    def setupCVSMNetapp(self):
        
        master = self.pool.master
        minsize = int(master.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(master.lookup("SR_NETAPP_MAXSIZE", 1000000))
        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        cvsm_vm = xenrt.TEC().registry.guestGet("CVSMSERVER")
        cvsmserver = xenrt.CVSMServer(cvsm_vm)
        cvsmserver.addStorageSystem(napp)
        self.cvsmsr = xenrt.lib.xenserver.CVSMStorageRepository(master, "cvsmsr")
        if master.lookup("USE_MULTIPATH", False, boolean=True):
            mp = True
        else:
            mp = None
            self.cvsmsr.create(cvsmserver,
                               napp,
                               protocol="iscsi",
                               physical_size=None,
                               multipathing=mp)
        
        self.cvsm_vm = cvsm_vm


    def prepare(self, arglist=None):
        
        self.pool = self.getDefaultPool()
        
        self.hosts = self.pool.getHosts()
        
        self.setupCVSMNetapp()

        cvsm_host = self.cvsm_vm.getHost()

        if cvsm_host is self.pool.master:
            xenrt.TEC().logverbose("CVSM VM is on the master")
            for h in self.hosts:
                if h != self.pool.master:
                    self.pool.designateNewMaster(h)
                    break

        self.pool.enableHA()       

        self.pool.paramSet("ha-host-failures-to-tolerate", "2")

        self.installVMs()
        

    def killSetOfHosts(self, hosts):
        
        xenrt.TEC().logverbose("stopping xapi on %s and %s" % 
                               (hosts[0].getName(),hosts[1].getName()))

        if self.pool.master in hosts:
            xenrt.XRTError("master is one of the hosts whose xapi will be stopped")

        for h in hosts:
            h.execdom0("touch /etc/xensource/xapi_block_startup")
            if h.isCentOS7Dom0():
                h.execdom0("systemctl stop xapi.service")
                h.execdom0("systemctl disable xapi.service")
            else:
                h.execdom0("mv /etc/init.d/xapi /etc/init.d/xapi.disabled")
                h.execdom0("/etc/init.d/xapi.disabled stop")
        
        cli = self.pool.getCLIInstance()
        for h in hosts:
            cli.execute("event-wait class=host uuid=%s host-metrics-live=false" % h.getMyHostUUID())


    def bringUpHosts(self, hosts):
        
        xenrt.TEC().logverbose("Repairing the hosts so that it rejoin pool")
        time.sleep(180)

        for h in hosts:
            h.waitForSSH(900, desc="host reboot after host fence")
            h.execdom0("rm -f /etc/xensource/xapi_block_startup")
            if h.isCentOS7Dom0():
                h.execdom0("systemctl enable xapi.service")
            else:
                h.execdom0("mv /etc/init.d/xapi.disabled /etc/init.d/xapi")
            h.startXapi()


        cli = self.pool.getCLIInstance()
        for h in hosts:
            cli.execute("event-wait class=host uuid=%s host-metrics-live=true" % h.getMyHostUUID())
        
        for h in hosts:
            cli.execute("event-wait class=host uuid=%s enabled=true" % h.getMyHostUUID())


    def waitForAllVMsToBeUp(self):

        cli = self.pool.getCLIInstance()
        
        for g in self.guests:
            cli.execute("event-wait class=vm uuid=%s power-state=running" % g.getUUID())
        
        cli.execute("event-wait class=vm uuid=%s power-state=running" % 
                    self.cvsm_vm.getUUID())


    def moveAllVMs(self, to_hosts):

        self.cvsm_vm.migrateVM(to_hosts[0], live="true")
        
        for i in range(4):
            self.guests[i].migrateVM(to_hosts[0], live="true")

        for i in range(4,9):
            self.guests[i].migrateVM(to_hosts[1], live="true")


    def calculateRestartTime(self, hosts, diff_times):

        time_1 = time.time()

        self.killSetOfHosts(hosts)
        self.waitForAllVMsToBeUp()

        time_2 = time.time()

        diff_time = time_2 - time_1

        xenrt.TEC().logverbose("start time (%s) end time (%s) diff (%s)" %
                               (time_1, time_2, diff_time))

        diff_times.append(diff_time)

        xenrt.TEC().logverbose("Bringing up %s and %s" % 
                               (hosts[0].getName(),hosts[1].getName()))

        self.bringUpHosts(hosts)

        self.moveAllVMs(hosts)


    def run(self, arglist=None):
        diff_time_run_1 = list()
        diff_time_run_2 = list()

        # We know that it's the  first set that has the VMs

        for i in range(10):
            xenrt.TEC().logverbose("Iteration %s" % i)
            self.calculateRestartTime(self.hosts_1, diff_time_run_1)
                
        xenrt.TEC().logverbose("Setting the CVSMSERVER restart priority to 0")
        self.cvsm_vm.setHAPriority(0)

        for i in range(10):
            xenrt.TEC().logverbose("Iteration %s" % i)
            self.calculateRestartTime(self.hosts_1, diff_time_run_2)
            
        average_time_1 = sum(diff_time_run_1)/len(diff_time_run_1)
        
        average_time_2 = sum(diff_time_run_2)/len(diff_time_run_2)
        
        xenrt.TEC().logverbose("Average restart time in seconds before (%s)  after(%s)" %
                               (average_time_1, average_time_2))
        
        if average_time_1 < average_time_2:
            raise xenrt.XRTFailure("Average restart time with StorageLink VM set to "
                                   "higher restart priority(0) is no better")
        

    def postRun(self):
        
        #. Unprotect all the VMs
        for g in self.guests:
            g.setHAPriority(protect=False)
        
        self.cvsm_vm.setHAPriority(protect=False)

        #. Disable HA
        self.pool.disableHA()

        #. Uninstall VMs
        for g in self.guests:
            g.uninstall()
        
        return 


class _HASnapshotTest(_HATest):
    """Regression test for CA-60543 - Filesystem of VM became read-only after snap delete with HA"""
    
    def run(self, arglist=None):
        
        host0 = self.getHost("RESOURCE_HOST_0")
        slave = self.getHost("RESOURCE_HOST_1")
        
        # don't enable HA now - this needs to be done later
        pool = self.configureHAPool([host0, slave], enable=False)

        origVMName = "origVM"
        cloneVMName = "cloneVM"
        
        # create a VM on a slave on the HA SR and convert it to a template
        origVm = slave.createGenericLinuxGuest(name=origVMName, sr=self.sr.uuid)
        self.uninstallOnCleanup(origVm)
        origVm.shutdown()
        origVm.paramSet("is-a-template", "true")
        vifUUID = origVm.getVIFUUID("eth0")
        mac = host0.genParamGet("vif", vifUUID, "MAC")
        netuuid = host0.genParamGet("vif", vifUUID, "network-uuid")

        # create a new VM from the template on the slave
        cloneVm = slave.guestFactory()(cloneVMName, template=origVMName, host=slave)
        cloneVm.createGuestFromTemplate(cloneVm.template, sruuid=self.sr.uuid)
        self.uninstallOnCleanup(cloneVm)
        cloneVm.removeVIF("eth0")
        cloneVm.createVIF("eth0", bridge=netuuid, mac=mac)
        cloneVm.start()

        # enable HA
        pool.enableHA()
        pool.setPoolParam("ha-host-failures-to-tolerate", "1")
        
        time.sleep(30)

        # take a snapshot of the cloned VM and then delete the snapshot
        snapShotUuid = cloneVm.snapshot()
        cloneVm.removeSnapshot(snapShotUuid)

        for i in range(10):
            time.sleep(30)
            cloneVm.checkHealth()
            cloneVm.execguest("ls")
        
class TC14984(_HASnapshotTest):
    SF_STORAGE = "iscsi"

class TC14985(_HASnapshotTest):
    SF_STORAGE = "nfs"

class TC26903(_HASnapshotTest):
    SF_STORAGE = "nfs4"

class TC14986(_HASnapshotTest):
    SF_STORAGE = "fc"

class TCHaVmImport(xenrt.TestCase):
    """For 5.x hosts, VM ha_restart_priority can be set to a number: 1,2,3
       If such VM is imported into a 6.x host, ha_restart_priority should get converted to "restart", 
       with the order param taking up the previous value
       e.g. "1"->ha_restart_priority="restart", order="1"."""
              
    def run(self,arglist):
        
        host = self.getDefaultHost()
        host1 = self.getHost("RESOURCE_HOST_1")
        
        step("Create a VM on the 5.x host")
        guest = host.createGenericLinuxGuest()
        #shut down the guest
        guest.shutdown()
          
        step("Set the ha_restart_priority values to 1,2,3 and then export the VM")
        tmp = xenrt.resources.TempDirectory()
        image = "%s/%s" % (tmp.path(), guest.getName())
        for i in range(1,4):
          guest.paramSet("ha-restart-priority",i)
          step("Export the vm with ha_restart_priority = %d as an .xva" %i)
          guest.exportVM(image + str(i))
        
        #uninstall the vm
        guest.uninstall()
                
        for i in range(1,4):
          step("Import the VM with ha_restart_priority = %d on the 6.x host" %i)
          guest.importVM(host1, image + str(i), sr = host1.lookupDefaultSR())
          
          step("Get the ha_restart_priority value for the new VM")
          ha_priority = guest.paramGet("ha-restart-priority")
          
          step("Verify the ha_restart_priority value for the new VM")
          if ha_priority == "restart":
            log("The import operation succesfully converts the ha_restart_priority value from %d to %s" %(i,ha_priority))
          else:
            raise xenrt.XRTFailure("Expected ha_restart_priority to be \"restart\", found to be %s" %ha_priority)
          #uninstall the vm
          guest.uninstall()
        
class TCStorageNICMTU(xenrt.TestCase):
    """TC-20626 Test case to test if MTU is getting applied to storage NICs when booting up with HA enabled (HFX-868, HFX-867) """
    SR = "lvmoiscsi"

    def prepare(self, arglist=None):
        # Get pool object
        pool = self.getDefaultPool()

        # Find an appropriate SR to use
        srs = pool.master.getSRs(type=self.SR)
        if len(srs) == 0:
            raise xenrt.XRTError("No SRs of type %s found" % (self.SR))
        self.statefileSR = srs[0]

        #create Generic Linux VM
        self.guest = pool.master.createGenericLinuxGuest(sr=self.statefileSR)

    def run(self, arglist=None):
        pool = self.getDefaultPool()
        slave = pool.getSlaves()[0]
        step("Fetch storage NIC")
        networkUUID =  pool.master.parseListForUUID("network-list", "other-config:xenrtnetname", "NPRI")
        masterpifUUID = pool.master.parseListForUUID("pif-list", "host-uuid", pool.master.getMyHostUUID(), "network-uuid=%s" % (networkUUID))
        device = pool.master.parseListForParam("pif-list", masterpifUUID, "device", "network-uuid=%s" % (networkUUID))
        bridge = pool.master.parseListForParam("network-list", networkUUID, "bridge")
        
        step("Set MTU of storage NICs to 9000")
        slavepifUUID = slave.getPIFUUID(device)
        
        pool.master.genParamSet("pif", masterpifUUID, "other-config", "Storage", pkey="management_purpose")
        pool.master.genParamSet("pif", slavepifUUID, "other-config", "Storage", pkey="management_purpose")
        pool.master.genParamSet("pif", masterpifUUID, "other-config", "9000", pkey="mtu")
        pool.master.genParamSet("pif", slavepifUUID, "other-config", "9000", pkey="mtu")

        step("Enable HA on the pool")
        pool.enableHA(srs=[self.statefileSR])
        # Set nTol to 1
        pool.setPoolParam("ha-host-failures-to-tolerate", 1)
        self.guest.setHAPriority(1)

        step("Reboot Master Host")
        #rebooting twice because sometimes error occurs on second reboot
        try:
            pool.master.reboot()
            xenrt.sleep(30)
            pool.master.reboot()
            xenrt.sleep(30)
        except: pass

        step("Verify %s and %s MTU are same" % (device, bridge))
        ethMTU = slave.execcmd("ifconfig %s | grep -Eoi 'MTU:? ?[0-9]+'|  grep -oE '[0-9]+'" % (device))
        xenbrMTU = slave.execcmd("ifconfig %s | grep -Eoi 'MTU:? ?[0-9]+'|  grep -oE '[0-9]+'" % (bridge))
        if ethMTU != xenbrMTU and ethMTU != "9000":
            raise xenrt.XRTFailure("MTU not as expected. %s MTU=%s %s MTU=%s" % (device, ethMTU, bridge, xenbrMTU))
        else:
            log("MTU as expected. %s MTU=%s %s MTU=%s" % (device, ethMTU, bridge, xenbrMTU))
            
class TCHaRestartProtectedVms(_HATest):
    """Verify that the protected VM's get restarted on other hosts in case of Host failure in a HA enabled pool"""
    SR = "nfs"

    def prepare(self, arglist=None):
        # Get pool object
        self.pool = self.getDefaultPool()
        self.statefileSR = self.pool.master.getSRs(type=self.SR)

        self.host1=self.getHost("RESOURCE_HOST_1")
        self.hostsToPowerOn = []
        #Create a setup given in CA-151670:A pool of 3 host having equal memory 
        #Each host has a running vm with memory V such that 0.33H <V<0.5H(H being the free memory in each host)
        #Keep the VM in one of the slaves protected (other VMs unprotected) and power off the host having protected VM

        self.guest1=self.getGuest("Deb1")
        self.guest2=self.getGuest("Deb2")
        self.guest3=self.getGuest("Deb3")

        freemem = self.host1.getFreeMemory()
        guestmem = int(0.4*(freemem+self.guest1.memory))

        allguests = [self.guest1,self.guest2,self.guest3]

        for guest in allguests:
            guest.shutdown()
            guest.setMemoryProperties(guestmem,guestmem,guestmem,guestmem)
            guest.start()

        self.guest1.setHAPriority(protect=False, restart=False)
        self.guest2.setHAPriority(protect=True, restart=True)
        self.guest3.setHAPriority(protect=False, restart=False)

    def run(self, arglist=None):

        step("Enable HA on the pool")
        self.pool.enableHA(srs=self.statefileSR)
        # Set nTol to 1
        self.pool.setPoolParam("ha-host-failures-to-tolerate", 1)

        self.hostsToPowerOn.append(self.host1)
        self.host1.machine.powerctl.off()        
        self.pool.haLiveset.remove(self.host1.getMyHostUUID())
        self.pool.sleepHA("W",multiply=3)

        #Verfiy that the protected guest is up
        if not self.guest2.findHost():
            raise xenrt.XRTFailure("Protected Guest %s failed to reappear"%self.guest2.getName())
        else :
            self.guest2.check()

