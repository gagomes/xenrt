#
# XenRT: Test harness for Xen and the XenServer product family
#
# Persistent Stats (RRD) Testcases
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, threading
import urllib, xml.dom.minidom
import xenrt, xenrt.lib.xenserver
import calendar
from xenrt.lazylog import step, comment, log, warning

class _RRDBase(xenrt.TestCase):
    """Base class for RRD related tests"""
    FIST_POINTS = [] # Any FIST points to enable for this TC
    START_VM = True # Start the vm or not
    NEED_SLAVE = True
    VM_ON_SLAVE = False # Run the VM on the slave
    USE_NFS = False # Use an NFS SR for the VM

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.master = None
        self.slave = None
        self.pool = None
        self.guest = None
        self.startTime = None

    def prepare(self, arglist=None):
        # Set up a pool of two machines, and install a VM.
        self.master = self.getHost("RESOURCE_HOST_0")
        self.master.resetToFreshInstall()
        if self.NEED_SLAVE:
            self.slave = self.getHost("RESOURCE_HOST_1")
            self.slave.resetToFreshInstall()

        self.pool = xenrt.lib.xenserver.poolFactory(self.master.productVersion)(self.master)

        if self.NEED_SLAVE:
            self.pool.addHost(self.slave)

        # Enable any FIST points and restart xapi...
        for fp in self.FIST_POINTS:
            for h in self.pool.getHosts():
                h.execdom0("touch /tmp/%s" % (fp))

        if len(self.FIST_POINTS) > 0:
            self.pool.master.restartToolstack()
            time.sleep(60)
            for h in self.pool.getSlaves():
                h.restartToolstack()
                time.sleep(30)
            time.sleep(30)

        sr = None
        try:
            sr = self.master.getLocalSR()
        except:
            pass

        if self.USE_NFS or not sr:
            # Create an NFS SR
            nfs = xenrt.ExternalNFSShare()
            nfsMount = nfs.getMount()
            r = re.search(r"([0-9\.]+):(\S+)", nfsMount)
            if not r:
                raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfsMount))
            nfsSR = xenrt.lib.xenserver.NFSStorageRepository(self.master, "NFS")
            nfsSR.create(r.group(1), r.group(2))
            sr = nfsSR.uuid

        if self.VM_ON_SLAVE:
            self.guest = self.slave.createGenericLinuxGuest(start=False, sr=sr)
        else:
            self.guest = self.master.createGenericLinuxGuest(start=False, sr=sr)

        # Remove any existing RRDs for this guest
        self.master.execdom0("rm -f /var/xapi/blobs/rrds/%s.gz || true" % 
                             (self.guest.getUUID()))
        self.startTime = xenrt.util.timenow()
        self.guest.start()

    def waitUntil(self, seconds, sleepFor=5):
        # Wait until <seconds> after VM start
        while (xenrt.util.timenow() - self.startTime) < seconds:
            time.sleep(sleepFor)

    def getGuestRRD(self):
        host = self.guest.host
        xenrt.TEC().logverbose("Attempting to get RRD from %s" %
                               (host.getName()))
        host.findPassword()
        url = "http://root:%s@%s/vm_rrd?uuid=%s" % (host.password,
                                                    host.getIP(),
                                                    self.guest.getUUID())
        u = urllib.urlopen(url)
        data = u.read()
        return xml.dom.minidom.parseString(data)

    def rrdTimestamp(self, guest, host, persistent=False, gzipped=True):
        """Returns the timestamp of an RRD for the specified guest on the
           specified host, or None if the RRD is not found"""
        if persistent:
            pers = ".persistent"
        else:
            pers = ""
        if gzipped:
            gz = ".gz"
        else:
            gz = ""
        try:
            return int(host.execdom0("stat -c %%Y /var/xapi/blobs%s/rrds/%s%s" %
                                     (pers, guest.getUUID(), gz)).strip())
        except:
            return None

# TC-8240 - RRD file size and ageing
class TC8244(_RRDBase):
    """Verify that RRD granularities are obeyed"""    
    FIST_POINTS = ["fist_reduce_rra_times"] # This changes the times to 5s/10m,
                                            # 1m/20m, 2m/30m, 3m/30m.

    def run(self, arglist=None):
        # Wait until just past 9 minutes and then check we have:
        # 108, 9, 4, 3
        self.waitCheck(9,(120,19,6,4), (12,10,4,2))

        # Wait until just past 19m, and check we have:
        # 120, 19, 9, 6
        self.waitCheck(19,(120,19,13,8), (0,1,4,3))

        # Wait until just past 29m, and check we have:
        # 120, 20, 14, 9
        self.waitCheck(29,(120,20,14,9), (0,0,1,1))

        # Wait until just past 35m, and check we have:
        # 120, 20, 15, 10
        self.waitCheck(35,(120,20,15,10), (0,0,0,0))

        # Wait until just past 1h, and check we have:
        # 120, 20, 15, 10
        self.waitCheck(60,(120,20,15,10), (0,0,0,0))    

    def waitCheck(self, minutes, dataPoints, allowedVariances):
        """Wait until <minutes> after starting the VM and check we have the
           expected number of data points in each category"""

        self.waitUntil((minutes * 60) + 10)

        # Check the RRDs
        rrd = self.getGuestRRD()
        # Find the requisite rras
        rras = rrd.getElementsByTagName("rra")
        dataPointsChecked = 0
        for rra in rras:
            # We only look at AVERAGE for now
            cfs = rra.getElementsByTagName("cf")
            if cfs[0].childNodes[0].data != "AVERAGE":
                continue
            pprs = rra.getElementsByTagName("pdp_per_row")
            ppr = int(pprs[0].childNodes[0].data)
            db = rra.getElementsByTagName("database")[0]
            rows = db.getElementsByTagName("row")
            timescale = (len(rows),ppr)
            expect = 0
            variance = 0
            desc = ""
            if timescale == (120,1):
                desc = "5s/10m"
                expect = dataPoints[0]
                variance = allowedVariances[0]
            elif timescale == (20,12):
                desc = "1m/20m"
                expect = dataPoints[1]
                variance = allowedVariances[1]
            elif timescale == (15,24):
                desc = "2m/30m"
                expect = dataPoints[2]
                variance = allowedVariances[2]
            elif timescale == (10,36):
                desc = "3m/30m"
                expect = dataPoints[3]
                variance = allowedVariances[3]
            else:
                raise xenrt.XRTError("Unknown RRA timescale (%u,%u) found" % 
                                     timescale)
            found = 0
            for row in rows:
                val = row.childNodes[0].childNodes[0].data
                xenrt.log("Value is %s" % val)
                if val != "NaN":
                    found += 1
            if (found < expect and (found + variance) < expect) or \
               (found > expect and (found - variance) > expect): 
                raise xenrt.XRTFailure("Incorrect number of data points for "
                                       "%s timescale" % (desc),
                                       data="Expecting %u, found %u" % 
                                            (expect, found))
            xenrt.TEC().logverbose("Checked timescale %s" % (desc))
            dataPointsChecked += 1
        if dataPointsChecked != 4:
            raise xenrt.XRTFailure("Only found %u/4 timescales" % 
                                   (dataPointsChecked))

# TC-8241 - RRD Persistence
class TC8245(_RRDBase):
    """Verify that RRDs associated with running VMs are backed up to the master
       every 24 hours"""
    FIST_POINTS = ["fist_reduce_rrd_backup_interval"] # Back up RRDs every 5m,
                                                      # starting after 6m
    VM_ON_SLAVE = True
    USE_NFS = True

    def run(self, arglist=None):
        # Wait 6m, and check that the RRD has been synced
        time.sleep(360)
        ts1 = self.rrdTimestamp(self.guest, self.master)
        if not ts1:
            raise xenrt.XRTFailure("RRD not backed up to master when expected")

        # Now wait for another 5m and make sure that it's been updated
        time.sleep(300)

        ts2 = self.rrdTimestamp(self.guest, self.master)
        if not ts2 > ts1:
            raise xenrt.XRTFailure("RRD not updated when expected")

        # And again
        time.sleep(300)

        ts3 = self.rrdTimestamp(self.guest, self.master)
        if not ts3 > ts2:
            raise xenrt.XRTFailure("RRD not updated when expected (2)")

class TC8246(_RRDBase):
    """Verify that the pool master syncs out all RRDs to slaves every 24 hours"""
    FIST_POINTS = ["fist_reduce_rrd_backup_interval",
                   "fist_reduce_blob_sync_interval"] # Sync every 5m, starting
                                                     # after 10m.

    def run(self, arglist=None):
        # Wait 10m and check that the RRD has appeared on the slave
        time.sleep(600)
        ts1 = self.rrdTimestamp(self.guest, self.slave)
        if not ts1:
            raise xenrt.XRTFailure("RRDs not backed up to slave when expected")        

        # Wait another 5m and check that it's been updated
        time.sleep(300)

        ts2 = self.rrdTimestamp(self.guest, self.slave)
        if not ts2 > ts1:
            raise xenrt.XRTFailure("RRD not updated when expected")

        # And again
        time.sleep(300)

        ts3 = self.rrdTimestamp(self.guest, self.slave)
        if not ts3 > ts2:
            raise xenrt.XRTFailure("RRD not updated when expected (2)")


# TC-8242 - RRD Pool Operations
class TC8247(_RRDBase):
    """Verify that a clean master transition correctly syncs RRDs to the new 
       master"""

    def run(self, arglist=None):
        # Shut down the VM
        self.guest.shutdown()

        # Wait a little bit to make sure the RRD file transfer was completed
        time.sleep(10)

        # Check the RRD exists on the master
        if not self.rrdTimestamp(self.guest, self.master):
            raise xenrt.XRTError("RRD not present on master")
        # Verify it doesn't exist on the slave
        if self.rrdTimestamp(self.guest, self.slave):
            raise xenrt.XRTError("RRD already present on slave")

        # Change master
        self.pool.designateNewMaster(self.slave)

        # See if the RRD exists on the slave now
        if not self.rrdTimestamp(self.guest, self.slave):
            raise xenrt.XRTFailure("RRD not found on new master after clean "
                                   "master transition")

        # Check the slave actually returns it
        self.guest.host = self.slave
        try:
            self.getGuestRRD()
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Exception when retrieving RRD from xapi")


class TC8248(_RRDBase):
    """Verify that a past 'backup' of RRDs are used if the master fails 
       unexpectedly"""
    FIST_POINTS = ["fist_reduce_rrd_backup_interval",
                   "fist_reduce_blob_sync_interval"] # So we have a backup

    def run(self, arglist=None):
        # Wait 10m to ensure we get a backup
        time.sleep(600)

        # Shutdown the guest
        self.guest.shutdown()
        # Sync the database so the slave knows its offline
        self.pool.syncDatabase()

        # Fail the master
        self.master.machine.powerctl.off()

        # Wait 3m for the slave to realise
        time.sleep(180)

        # Perform an emergency mode transition on the slave
        self.pool.setMaster(self.slave)
        self.guest.host = self.slave

        # Check we can still get stats for the VM
        try:
            rrd = self.getGuestRRD()
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Expection %s while running getGuestRRD()" %
                                   (str(e)))
            raise xenrt.XRTFailure("'Backup' RRD not used after unexpected "
                                   "master failure")           

    def preLogs(self):
        try:
            self.master.machine.powerctl.on()
        except:
            pass

        self.master.waitForSSH(600, desc="Host boot after power on")

class TC8262(_RRDBase):
    """Verify that on migrate RRDs are correctly synced between hosts"""
    USE_NFS = True

    def run(self, arglist=None):
        # Leave the VM so it's been running for at least 10 minutes
        time.sleep(600)

        # Now migrate it
        self.guest.migrateVM(self.slave, live="true")

        # Now get the stats and see what happens
        rrd = self.getGuestRRD()
        # Check we have a full 10 minute RRA
        rras = rrd.getElementsByTagName("rra")
        found = 0
        for rra in rras:
            cfs = rra.getElementsByTagName("cf")
            if cfs[0].childNodes[0].data != "AVERAGE":
                continue
            pprs = rra.getElementsByTagName("pdp_per_row")
            ppr = int(pprs[0].childNodes[0].data)
            db = rra.getElementsByTagName("database")[0]
            rows = db.getElementsByTagName("row")
            timescale = (len(rows),ppr)
            if timescale != (120, 1):
                continue
            for row in rows:
                val = row.childNodes[0].childNodes[0].data
                xenrt.log("Value is %s" % val)
                if val != "NaN":
                    found += 1
            break

        if found != 120:
            raise xenrt.XRTFailure("RRD does not appear to have been correctly "
                                   "synced across after live migrate",
                                   data="Found %u points in 5s/10m RRA, "
                                        "expecting 120" % (found))

class TC8287(_RRDBase):
    """Verify RRDs remain after a clean host-reboot"""
    FIST_POINTS = ["fist_reduce_rrd_backup_interval"]
    
    def run(self, arglist=None):
        # Leave it running for 6 minutes to get it backed up
        time.sleep(360)

        # Shut down the guest
        self.guest.shutdown()

        # Check it exists before reboot
        if not self.rrdTimestamp(self.guest, self.master):
            raise xenrt.XRTError("Backed up RRD doesn't exist before reboot")

        # Reboot the master
        self.master.cliReboot()

        # Check it exists now
        if not self.rrdTimestamp(self.guest, self.master):
            raise xenrt.XRTFailure("Backed up RRD vanished after clean reboot")

        # Check it can be accessed
        try:
            self.getGuestRRD()
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            raise xenrt.XRTFailure("Exception when retrieving RRD from xapi")



# TC-8243 - Data Sources
class TC8249(_RRDBase):
    """Verify that VM data source operations work as expected"""
    DSOURCES_STD = ["cpu0",
                    "vif_0_tx","vif_0_rx","vif_0_rx_errors","vif_0_tx_errors",
                    "vbd_xvdb_write","vbd_xvdb_read","vbd_xvdb_read_latency",
                    "vbd_xvdb_write_latency",
                    "vbd_xvda_write","vbd_xvda_read","vbd_xvda_read_latency",
                    "vbd_xvda_write_latency",
                    "memory", "memory_internal_free"]

    def run(self, arglist=None):
        raise xenrt.XRTError("Unimplemented - waiting on CA-23550")

class TC8250(_RRDBase):
    """Verify the vm-data-source-forget command works as expected"""

    def run(self, arglist=None):
        raise xenrt.XRTError("Unimplemented - waiting on CA-23550")

# TC-8261 - RRD Correctness Tests
class TC8306(_RRDBase):
    """Verify that the CPU usage measurement is correctly pulled into RRDs"""
    NEED_SLAVE = False

    def run(self, arglist=None):        
        # Leave the VM idle for 10 minutes.
        xenrt.TEC().logverbose("Leaving VM idle for 10 minutes")
        time.sleep(600)
        xenrt.TEC().logverbose(" ... done")

        # Generate 100% CPU usage for 5 minutes
        xenrt.TEC().logverbose("Generating 100% CPU usage for 5 minutes")
        self.guest.execguest("touch /tmp/doload")
        self.guest.execguest("while [ -e /tmp/doload ]; do true; done > "
                             "/dev/null 2>&1 < /dev/null &")
        time.sleep(300)
        xenrt.TEC().logverbose(" ... done")

        #Grab the RRD
        rrd = self.getGuestRRD()
        # (Stop the CPU load)
        self.guest.execguest("rm -f /tmp/doload")

        # We expect the first ~60 values with CPU usage below 0.035 (changed from 1% to 3.5%)
        # The last ~60 values should have CPU usage above 0.9
        # Generate a list of values
        rras = rrd.getElementsByTagName("rra")
        rra = rras[0] # The first one is 5s/10m
        dbs = rra.getElementsByTagName("database")
        db = dbs[0] # There's only one
        # Get all the rows
        rows = db.getElementsByTagName("row")
        # Go through the first 60
        belowCount = 0
        #Get the value of count, Adding this code because new performance plugins have been added, so before cpu0 
        #there will be other metrics
        ds=rrd.getElementsByTagName("ds")
        for d in ds:
          name=d.getElementsByTagName("name")
          if name[0].childNodes[0].data=="cpu0":
            count=ds.index(d)
            break

        for i in range(60):
            vals = rows[i].getElementsByTagName("v")
            if float(vals[count].childNodes[0].data) < 0.035: # using .035, because there may be rrd values in the range of .01-.035
                belowCount += 1
        if belowCount < 58: 
            # This means there aren't enough idle points
            raise xenrt.XRTFailure("Didn't find enough idle values in RRD",
                                   data="Expected 58+, found %u" % (belowCount))
                                   
        # Go through the last 60
        aboveCount = 0
        for i in range(60):
            vals = rows[i+60].getElementsByTagName("v")
            if float(vals[count].childNodes[0].data) > 0.9:
                aboveCount += 1
        if aboveCount < 58:
            # This means there aren't enough high points
            raise xenrt.XRTFailure("Didn't find enough high values in RRD",
                                   data="Expected 58+, found %u" % (aboveCount))
 

class TC8911(_RRDBase):
    """Verify that RRDs are removed when VMs are destroyed, in both blobs and
       blobs.persistent"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Waiting 30 seconds to ensure data is collected")
        time.sleep(30)

        xenrt.TEC().logverbose("Shutting down VM")
        self.guest.shutdown()

        xenrt.TEC().logverbose("Rebooting host to ensure RRD is copied to "
                               "blobs.persistent on OEM edition")
        self.host.reboot()

        xenrt.TEC().logverbose("Uninstalling VM")
        self.guest.uninstall()

        xenrt.TEC().logverbose("Rebooting host to ensure RRD is not recovered "
                               "from blobs.persistent on OEM edition")
        self.host.reboot()

        xenrt.TEC().logverbose("Verifying RRD does not exist")
        # Verify the RRD does not exist in /var/xapi/blobs/rrds
        if self.rrdTimestamp(self.guest, self.host):
            raise xenrt.XRTFailure("RRD found in /var/xapi/blobs/rrds after VM "
                                   "had been uninstalled")         

class TC18873(xenrt.TestCase):
    
    """Verify rrdd can cope with metric payloads >16KiB (HFX-501)"""
    
    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        
    def run(self, arglist=None):
        try:
            xenrt.TEC().logverbose("Restarting Toolstack")
            self.host.restartToolstack()
            #Wait until logs to get generated
            xenrt.sleep(200)
        except xenrt.XRTException, e:
            raise e
        
        xenrt.TEC().logverbose("Checking the size of metric payload file")
        rddFileSize = self.host.execdom0("ls -l /dev/shm/metrics/xcp-rrdd-xenpm").split(' ')[4]
        if( rddFileSize < 16*1024):
            raise xenrt.XRTFailure("Failed to Generate Metric payload >16KiB")
        
        xenrt.TEC().logverbose("Verify that the timestamp on the fifth line of /dev/shm/metrics/xcp-rrdd-xenpm changes every 5 seconds")
        timeStamp1 = self.host.execdom0("sed -n '5p' /dev/shm/metrics/xcp-rrdd-xenpm").split(':')[1];
        xenrt.sleep(5)
        timeStamp2 = self.host.execdom0("sed -n '5p' /dev/shm/metrics/xcp-rrdd-xenpm").split(':')[1];
        if (timeStamp1 == timeStamp2):
            raise xenrt.XRTError("Timestamps in /dev/shm/metrics/xcp-rrdd-xenpm hasn't changed after 5 seconds")
        
        xenrt.TEC().logverbose("Check rrd2csv show new data every 5 seconds")
        self.host.execdom0("nohup rrd2csv cpu0-C0>temp.txt &")
        xenrt.sleep(20)
        self.host.execdom0("cat temp.txt")
        timeStamp1 = self.host.execdom0("head -3 temp.txt | tail -1").split('Z')[0]
        timeStamp2 = self.host.execdom0("head -4 temp.txt | tail -1").split('Z')[0]
        self.host.execdom0("pkill rrd2csv")
        if ( (int(calendar.timegm(time.strptime(timeStamp2, "%Y-%m-%dT%H:%M:%S")))) - (int(calendar.timegm(time.strptime(timeStamp1, "%Y-%m-%dT%H:%M:%S")))) != 5):
            raise xenrt.XRTError("rrd2csv doesn't show new data after 5 seconds")
            
class TC19888(xenrt.TestCase):
    """Verify that non-default data sources (epic DS) can be turned on and off"""

    def getNumberofDS(self, host):
        len=host.execdom0("xe host-data-source-list | grep -B2 'enabled: true'| grep 'name_label'| wc -l")
        return len
        
    def getDSList(self, host):
        str=host.execdom0("xe host-data-source-list | grep -B2 'enabled: true'| grep 'name_label'")
        return str

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.dsList=self.getDSList(host=self.host)

    def run(self, arglist=None):
        self.runSubcase("enableNonDefaultDS", (self.host), "Epic Metrics", "Enable Non-Default DS")
        self.runSubcase("disableNonDefaultDS", (self.host), "Epic Metrics", "Disable Non-Default DS")
        
    def enableNonDefaultDS(self, host):
        xenrt.TEC().logverbose("Get the number of data sources in a fresh install")
        numBeforeEnable=self.getNumberofDS(host=host)
        xenrt.TEC().logverbose("The number of data sources in a fresh install is %s" % 
                                numBeforeEnable)

        # Enable the non-default DS, the number should then go up
        host.execdom0("xe-enable-all-plugin-metrics true")
        # Sleep for sometime to let the changes take effect
        xenrt.sleep(120)
        numAfterEnable=self.getNumberofDS(host)
        xenrt.TEC().logverbose("The number of data sources when non-default DS enabled is %s" % 
                                numAfterEnable)

        com=[]
        noncom=[]
        # Compare the ones that are same and print the extra metrics
        newDSList=self.getDSList(host=host)
        for item in newDSList:
            if item in self.dsList:
                com.append(item)
            else:
                noncom.append(item)
        xenrt.TEC().logverbose("The extra DS after enabling the epic metrics are %s " % 
                                noncom)

        if not noncom and numAfterEnable<=numBeforeEnable:
            raise xenrt.XRTFailure("No extra data sources found after anabling the non-default metrics")

    def disableNonDefaultDS(self, host):
        flag=host.execdom0("cat /etc/xcp-rrdd.conf | grep 'plugin-default = true'").strip()
        if not flag:
            host.execdom0("xe-enable-all-plugin-metrics true")
        xenrt.TEC().logverbose("Get the number of data sources before disabling")
        numBeforeDisable=self.getNumberofDS(host=host)
        dsListBeforeD=self.getDSList(host=host)
        xenrt.TEC().logverbose("The number of data sources before disabling non-default DS is %s" % 
                                numBeforeDisable)

        # Disable the non-default DS
        host.execdom0("xe-enable-all-plugin-metrics false")
        # Sleep for sometime to let the changes take effect
        xenrt.sleep(120)
        numAfterDisable=self.getNumberofDS(host=host)
        xenrt.TEC().logverbose("The number of data sources after disabling non-default DS is %s" % 
                                numAfterDisable)

        com=[]
        noncom=[]
        if numBeforeDisable != numAfterDisable:
            newDSList=self.getDSList(host=host)
            for item in dsListBeforeD:
                if item in newDSList:
                    com.append(item)
                else:
                    noncom.append(item)
            xenrt.TEC().logverbose("Number of common elements %i" % 
                                    len(com))
            xenrt.TEC().logverbose("Number of non-common elements %i " % 
                                    len(noncom))
            xenrt.TEC().logverbose("Found some data sources missing after running the disable command %s" %
                                    noncom)
            raise xenrt.XRTFailure("Number before disabling %s and after disabling %s differ, the extra DS are expected to be recorded unless cleaned" % 
                                    (numBeforeDisable, numAfterDisable))

        # Forget the extra DS
        host.execdom0("service xapi stop && service xcp-rrdd stop")
        host.execdom0("rm -rf /var/xapi/blobs/rrds/*")
        host.restartToolstack()

        newDSList=self.getDSList(host=host)
        numAfterCleanRRD=self.getNumberofDS(host=host)
        xenrt.TEC().logverbose("The number of data sources in a fresh install is %s" % 
                                numAfterCleanRRD)

        for item in newDSList:
            if item in self.dsList:
                com.append(item)
            else:
                noncom.append(item)

        if noncom and numAfterCleanRRD >= numBeforeDisable:
            xenrt.TEC().logverbose("Found some data sources which were not disabled after running the disable command %s" %
                                    noncom)
            raise xenrt.XRTError("Number of DS recorded when plugin=false not equal to number of DS after enable-disable of non-default DS")

class TC19896(TC19888):

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest=self.host.createGenericWindowsGuest()
        self.dsList=self.getDSList(host=self.host)


class TCXapiSessionLeak(xenrt.TestCase):
    """Check for XAPI session leak when host_rrd or vm_rrd is executed to member host. STCX-1211
       If leak occurs, HOST_IS_SLAVE exception is found, as API calls over HTTP to slaves may be blocked. """
         
    def run(self,arglist):
        pool = self.getDefaultPool()
        master = pool.master
        slave = pool.getSlaves()[0]

        step("Execute host_rrd on slave")
        startTime = xenrt.util.timenow() 
        while xenrt.util.timenow() < startTime + 10: 
           slave.execdom0("wget http://root:%s@%s/host_rrd" %(slave.password, slave.getIP()))
        
        step("Searching for the HOST_IS_SLAVE exception in xensource.log")
        msg = "Got exception HOST_IS_SLAVE"
        grepReturnValue = slave.execdom0("grep '%s' /var/log/xensource.log" %(msg),retval = "code")
        if grepReturnValue == 0:
            raise xenrt.XRTFailure("host_rrd request for slave causes HOST_IS_SLAVE exception.")
        else:
            log("host_rrd request for slave doesn't cause any HOST_IS_SLAVE exception")

class SRIOMetrics(xenrt.TestCase):
    """Check rrd2csv is reporting I/O metrics associated with the right SR when there are 2 SRs and I/O is done on 1 vbd(regression test for CA-103913)"""
    #jira TC20671

    def prepare(self, arglist=None):
        host = self.getDefaultHost()
        self.guest = host.createBasicGuest(distro="debian60")
        self.sr = host.getSRs(type="lvmoiscsi")

    def run(self,arglist):
        step("Create the VDIs on both SRs")
        host = self.getDefaultHost()
        guest=self.guest
        vdi=[]
        vdi.append(host.createVDI(xenrt.GIGA, self.sr[0], name="VDI0"))
        vdi.append(host.createVDI(xenrt.GIGA, self.sr[1], name="VDI1"))
        
        step("Create and attach vbds on VM for both SRs")
        cli = host.getCLIInstance()
        vbduuid=[]
        vbduuid.append(cli.execute("vbd-create", "vdi-uuid=%s vm-uuid=%s device=1" % (vdi[0], self.guest.getUUID())).strip())
        vbduuid.append(cli.execute("vbd-create", "vdi-uuid=%s vm-uuid=%s device=2" % (vdi[1], self.guest.getUUID())).strip())
        cli.execute("vbd-plug", "uuid=%s" % vbduuid[0])
        cli.execute("vbd-plug", "uuid=%s" % vbduuid[1])
        
        step("Format and mount vbds")
        device=host.genParamGet("vbd", vbduuid[0], "device")
        guest.execguest("mkdir /vbd0")
        guest.execguest("mkfs.ext3 /dev/%s" % device)
        guest.execguest("mount /dev/%s /vbd0" % device)
        device=host.genParamGet("vbd", vbduuid[1], "device")
        guest.execguest("mkdir /vbd1")
        guest.execguest("mkfs.ext3 /dev/%s" % device)
        guest.execguest("mount /dev/%s /vbd1" % device)
        xenrt.sleep(60)
        
        step("Write files to vbd0 and check io_throughput_total  values for both SRs")
        self.guest.execguest("nohup cp -r /root /usr /var /vbd0>temp.txt &")
        xenrt.sleep(2)
        xenrt.TEC().logverbose("Check rrd2csv io_throughput data for both SRs")
        host.execdom0("nohup rrd2csv io_throughput_total_%s>sr0.txt &" % (self.sr[0].split('-')[0]))
        host.execdom0("nohup rrd2csv io_throughput_total_%s>sr1.txt &" % (self.sr[1].split('-')[0]))
        xenrt.sleep(15)
        host.execdom0("pkill rrd2csv")
        
        success = 0
        try:
            for i in range(int(host.execdom0("cat sr0.txt | wc -l"))-1):
                ioThroughput0 = float(host.execdom0("head -%s sr0.txt | tail -1" % (str(i+2))).split('Z, ')[1])
                ioThroughput1 = float(host.execdom0("head -%s sr1.txt | tail -1" % (str(i+2))).split('Z, ')[1])
                if ioThroughput0 > 0 and ioThroughput1 == 0:
                    success = 1
                    break
        except Exception, e:
            if "list index out of range" in str(e):
                raise xenrt.XRTFailure("io_throughput_total metric not found: %s" % (str(e)))
            else:
                raise xenrt.XRTFailure("Exception occured while fetching io_throughput_total metric %s" % (str(e)))
        
        if success == 1:
            xenrt.TEC().logverbose('Success: Found expected io_throughput rrd')
        else:
            raise xenrt.XRTFailure('Error: Found io_throughput>0 on wrong SR')

class TC21700(xenrt.TestCase):
    """Check if the metrics output for IOPS corectly. Windows OS and NFS SR with PV Tools installed."""

    def prepare(self, arglist=None):
        host = self.getDefaultHost()
        self.sr = host.getSRs(type="nfs")
        self.guest = host.getGuest("Windows7")

        if not self.sr:
            raise xenrt.XRTError("Need NFS SR for testcase. None found.")
        if self.guest is None:
            raise xenrt.XRTError("Need Windows VM for testcase. None found.")

        self.WORKLOADS = ["IOMeter"]

        self.guest.installWorkloads(self.WORKLOADS)
        self.guest.shutdown()
        self.guest.start()

    def run(self, arglist=None):
        host = self.getDefaultHost()

        host.execdom0("xe-enable-all-plugin-metrics true")

        self.guest.workloads = self.guest.startWorkloads(self.WORKLOADS)

        xenrt.sleep(10)
        xenrt.TEC().logverbose("Check rrd2csv iops_total output.")
        host.execdom0("nohup rrd2csv iops_total_%s > iopslog.txt &" % (self.sr[0].split('-')[0]))
        xenrt.sleep(60)
        host.execdom0("pkill rrd2csv")

        self.guest.stopWorkloads(self.guest.workloads)

        results = []
        try:
            for i in range(int(host.execdom0("cat iopslog.txt | wc -l"))-1):
                parsedReply = host.execdom0("head -%s iopslog.txt | tail -1" % (str(i+2))).split('Z, ')[1]
                # Unexpected result in log sometimes.
                if parsedReply != 'N/A':
                    iops = float(parsedReply)
                    results.append(iops)
        except Exception, e:
            if "list index out of range" in str(e):
                raise xenrt.XRTFailure("iops_total metric not found: %s" % (str(e)))
            else:
                raise xenrt.XRTFailure("Exception occured while fetching iops_total metric.. %s" % (str(e)))

        xenrt.TEC().logverbose('\n'.join([str(i) for i in results]))

        # Analyse
        highestIOPS = 0;
        expectedMinimumIOPS = 10;

        for iops in results:
            if iops > highestIOPS:
                highestIOPS = iops

        if highestIOPS < expectedMinimumIOPS:
            raise xenrt.XRTFailure("iops_total metric output invalid: Maximum IOPS %s, expected at least %s" %
                                    (highestIOPS, expectedMinimumIOPS))
