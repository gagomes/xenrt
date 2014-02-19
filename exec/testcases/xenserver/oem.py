#
# XenRT: Test harness for Xen and the XenServer product family
#
# Tests specific to the OEM edition
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, shutil, os.path, stat, re, os, time, urllib, glob
import traceback
import xenrt, xenrt.lib.xenserver

class TCOEMUpdate(xenrt.TestCase):
    """Tests the OEM update functionality"""

    def __init__(self, tcid="TCOEMUpdate"):
        xenrt.TestCase.__init__(self, tcid)
        self.expectedBuild = "4.0.95-6269c"

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." %
                                 (machine))
        self.getLogsFrom(host)
        host.execdom0("rm -f /etc/xensource/skipsignature")

        # Extract the tarball to get the sample patch
        workdir = xenrt.TEC().getWorkdir()
        xenrt.getTestTarball("patchapply",extract=True,directory=workdir)

        # First check that patch-upload isn't allowed
        patchfile = "%s/patchapply/testpatch.asc" % (workdir)
        allowed = True
        try:
            host.applyPatch(patchfile)
        except xenrt.XRTFailure, e:
            allowed = False

        if allowed:
            raise xenrt.XRTFailure("Allowed to apply patch to an OEM host.")

        # Note down the current revision for later
        originalRevision = host.productRevision

        # Now check that update-upload works

        # First try an invalid update, to try and detect CA-23567
        xenrt.TEC().logverbose("Testing with invalid update to detect CA-23567")
        allowed = False
        try:
            host.applyOEMUpdate(patchfile, skipsig=False)
            allowed = True
        except:
            xenrt.TEC().logverbose("Expected exception attempting to upload "
                                   "invalid update")
        if allowed:
            raise xenrt.XRTError("Allow to upload invalid update")

        # Decide which update to use (build numbers > 7560 require specific
        # OEM signed updates - also test the other one to see what happens)
        # Strip out just the build number (avoid distinguishing between ga
        # and trunk).
        build = host.productRevision.split("-")[1]
        if int(re.sub("[a-zA-Z]", "", build)) > 7560:
            oubase = "%s/oemupdate/" % (xenrt.TEC().lookup("TEST_TARBALL_ROOT"))
            oem = string.split(host.getOEMManufacturer())[0]
            update = "%s/oem-%s.xsoem" % (oubase,oem)
            if not os.path.exists(update):
                raise xenrt.XRTError("Cannot find update for OEM "
                                     "manufacturer %s" % (oem))
            # Find the build number
            self.expectedBuild = xenrt.command("cat %s/oem-%s.ver" %
                                               (oubase,oem),strip=True)
        else:
            update = "%s/patchapply/oemupdate.patch" % (workdir)

        try:
            host.applyOEMUpdate(update, skipsig=False)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying update: " + e.reason)

        # Reboot the host to let the update go live
        host.reboot()

        # Check which build we are
        host.checkVersion()
        if host.productRevision != self.expectedBuild:
            raise xenrt.XRTFailure("After reboot host is %s, should be %s" %
                                   (host.productRevision,self.expectedBuild))

        # Set it back and reboot
        if host.execdom0("test -e /opt/xensource/libexec/set-boot",
                         retval="code") == 0:
            host.execdom0("/opt/xensource/libexec/set-boot alternate")
        else:
            host.execdom0("mount LABEL=IHVCONFIG /mnt")
            try:
                data = host.execdom0("cat /mnt/syslinux.cfg")
                ihvpart = host.execdom0("grep /mnt /proc/mounts | "
                                        "grep -v tmpfs | "
                                        "awk '{print $1}'").strip()
            finally:
                host.execdom0("umount /mnt")
            r = re.search(r"DEFAULT (\d+)", data)
            if not r:
                raise xenrt.XRTError("Could not determine bootable partition")
            if r.group(1) == "1":
                revert = 2
            elif r.group(1) == "2":
                revert = 1
            else:
                raise xenrt.XRTError("Do not understand the existing default "
                                     "bootable partition: %s" % (r.group(1)))
            host.execdom0("/opt/xensource/libexec/bootable.sh %s %u" %
                          (xenrt.extractDevice(ihvpart), revert))
        host.reboot(timeout=1200)

        # Check we get back the revision we had to start with
        host.checkVersion()
        if host.productRevision != originalRevision:
            raise xenrt.XRTFailure("Unable to get back original revision, got "
                                   "%s, should be %s." % (host.productRevision,
                                                          originalRevision))

class TCDBonSharedStorage(xenrt.TestCase):
    """Tests putting the DB on shared storage"""

    def __init__(self, tcid="TCDBonSharedStorage"):
        xenrt.TestCase.__init__(self, tcid)
        self.iscsi = None
        self.hostsToCleanup = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        pool = None
        poolname = None
        host = None

        if arglist and len(arglist) > 0:
            for arg in arglist:
                l = string.split(arg, "=", 1)
                if l[0] == "poolname":
                    poolname = l[1]
                elif l[0] == "host":
                    machine = l[1]

        if poolname:
            # This is a test in a pool case
            pool = xenrt.TEC().registry.poolGet(poolname)
            if not pool:
                raise xenrt.XRTError("Unable to find pool %s in registry." %
                                     (pool))
            host = pool.master
        else:
            host = xenrt.TEC().registry.hostGet(machine)
            if not host:
                raise xenrt.XRTError("Unable to find host %s in registry." %
                                     (machine))

        self.getLogsFrom(host)
        self.hostsToCleanup.append(host)

        if pool:
            self.iscsi = pool.setupSharedDB()
        else:
            iscsi = xenrt.lib.xenserver.host.ISCSILun()
            self.iscsi = iscsi

            # Start using it...
            if iscsi.chap:
                i, u, s = iscsi.chap
            else:
                u = "\"\""
                s = "\"\""

            try:
                host.setIQN(iscsi.getInitiatorName(allocate=True))
                host.execdom0("/etc/init.d/xapi stop")
                host.execdom0("python /opt/xensource/sm/shared_db_util.py "
                              "xenrt-setup %s %s %s %s %s" % 
                              (iscsi.getServer(),u,s,iscsi.getTargetName(),"0"))
                host.execdom0("/etc/init.d/xapi start")

            except xenrt.XRTFailure, e:
                raise xenrt.XRTFailure("Exception while setting up shared "
                                       "storage: " + str(e),data=e.data)

        # Start a write monitor going on the shared DB, and grab the value from
        # the existing one on the normal DB
        host.execdom0("mount")
        sharedDev = host.execdom0("mount | grep /var/xapi/shared_db | "
                                  "awk '{print $1}'")
        sharedDev = string.strip(sharedDev)
        if "iscsi" in sharedDev: # Mount is giving us a symlink
            dest = host.execdom0("readlink %s" % (sharedDev))
            # This will be of the form ../../sdc
            destbits = dest.strip().split("/")
            sharedDev = destbits[-1]
        else:
            # Just strip off the initial /dev/
            sharedDev = sharedDev[5:]
        host.enableWriteCounter(device=sharedDev)
        startFlashWrites = host.execdom0("tail -n 1 /var/log/xenrt-write-counte"
                                         "r.log | awk '{print $2}'")
        startFlashWrites = int(string.strip(startFlashWrites))
        startSharedWrites = host.execdom0("tail -n 1 /var/log/xenrt-write-count"
                                          "er-%s.log | awk '{print $2}'" %
                                          (sharedDev))
        startSharedWrites = int(string.strip(startSharedWrites))

        # Give it 5 minutes for some refreshes to happen etc
        time.sleep(300)

        # see what we did in terms of writes
        finalFlashWrites = host.execdom0("tail -n 1 /var/log/xenrt-write-counte"
                                         "r.log | awk '{print $2}'")
        finalFlashWrites = int(string.strip(finalFlashWrites))
        finalSharedWrites = host.execdom0("tail -n 1 /var/log/xenrt-write-count"
                                          "er-%s.log | awk '{print $2}'" %
                                          (sharedDev))
        finalSharedWrites = int(string.strip(finalSharedWrites))

        flashWrites = finalFlashWrites - startFlashWrites
        sharedWrites = finalSharedWrites - startSharedWrites

        xenrt.TEC().comment("%u flash writes during testing" % (flashWrites))
        xenrt.TEC().comment("%u shared writes during testing" % (sharedWrites))
        
        # Need to actually have some absolute values that we expect as well here
        # This is a partial pass, as it did work...
        if flashWrites > sharedWrites:
            self.setResult(xenrt.RESULT_PARTIAL)
            xenrt.TEC().warning("Flash writes > shared writes!")

        if pool:
            # Kill the master, and try and transition a slave to the master 
            # using the DB...
            oldmaster = host
            # Pick a new master and update the pool object (don't add current
            # master as we don't want to accidentally use it in the future
            newmastername = pool.slaves.keys()[0]
            newmaster = pool.slaves[newmastername]
            self.hostsToCleanup.append(newmaster)
            pool.setMaster(newmaster)
            self.hostsToCleanup.remove(oldmaster)
            
            # Check it all worked properly...
            pool.check()

    def postRun(self):
        # Make sure we stop using the iscsi lun
        for host in self.hostsToCleanup:
            try:
                self.cleanupHost(host)
            except xenrt.XRTFailure, e:
                xenrt.TEC().warning("Exception while cleaning up host %s" % 
                                    (host.getName()),data=e.data)

        if self.iscsi:
            self.iscsi.release()

    def cleanupHost(self,host):
        try:
            # May trigger an exception if the host is already stopped
            host.execdom0("/etc/init.d/xapi stop")
        except:
            pass

        try:
            host.execdom0("rm -f /etc/xensource/remote.db.conf")
            host.execdom0("/bin/cp -f /etc/xensource/local.db.conf "
                          "/etc/xensource/db.conf")
            host.execdom0("umount /var/xapi/shared_db")
        except xenrt.XRTFailure, e:
            xenrt.TEC().warning("Exception while cleaning up %s: %s" %
                                (host.getName(),e.reason))
        host.execdom0("/etc/init.d/xapi start")
