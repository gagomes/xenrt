#
# XenRT: Test harness for Xen and the XenServer product family
#
# Pool operations testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, shutil, os, re
import xenrt, xenrt.lib.xenserver
from testcases.xenserver.tc.upgrade import TCRollingPoolUpdate 
from xenrt import XRTError
from xenrt.lazylog import step, log

class _Hotfix(xenrt.TestCase):

    INITIAL_VERSION = "Miami"
    INITIAL_BRANCH = None
    INITIAL_HOTFIXES = []

    UPGRADE_VERSIONS = []
    UPGRADE_BRANCHES = []
    UPGRADE_HOTFIXES = []

    POOLED = False
    LICENSESKU = True
    CHECKVM = True
    EXTRASUBCASES = []
    SKIP_ON_FG_FREE_NO_ACTIVATION = False
    NEGATIVE = False
    CC = False

    def doHotfixesRetail(self, version, branch, hotfixes):
        for hf in hotfixes:
            patch = xenrt.TEC().lookup(["HOTFIXES", version, branch, hf.upper()])
            patches = self.host.minimalList("patch-list")
            if self.POOLED:
                self.pool.applyPatch(xenrt.TEC().getFile(patch))
                self.host.reboot()
                self.slave.reboot()
            else:
                self.host.applyPatch(xenrt.TEC().getFile(patch), patchClean=True)
                self.host.reboot()
                
                if "XS" in hf:
                    self.writeToUsrGroups(hf)
            
            patches2 = self.host.minimalList("patch-list")
            self.host.execdom0("xe patch-list")
            if len(patches2) <= len(patches):
                raise xenrt.XRTFailure("Patch list did not grow after patch application %s/%s" % (version, hf))
            xenrt.TEC().comment("Applied hotfix %s to initial version %s" % (hf, version))

    def writeToUsrGroups(self, hf):
        rpms = self.host.execdom0("rpm -qa|sort")
        dir  = '/usr/groups/xen/release-metadata'
        cmd = 'mkdir -p %s && echo "%s" > %s/%s' % (dir, rpms, dir, hf)
        xenrt.ssh.SSH(xenrt.TEC().lookup("MASTER_DISTFILES_SYNC_HOST"), cmd, "xenrtd")
    
    def doHotfixes(self, version, branch, hotfixes):
        self.doHotfixesRetail(version, branch, hotfixes)
    
    def preCheck(self):
        pass
    
    def postPrepare(self):
        pass

    def prepare(self, arglist):
        self.currentversion = None

        if self.SKIP_ON_FG_FREE_NO_ACTIVATION and xenrt.TEC().lookup("FG_FREE_NO_ACTIVATION", False, boolean=True):
            xenrt.TEC().skip("Skipping because FG_FREE_NO_ACTIVATION=yes")
            return

        if len(self.UPGRADE_VERSIONS) != len(self.UPGRADE_HOTFIXES):
            raise xenrt.XRTError("Upgrade versions and hotfixes config broken")

        # Perform the initial version install
        inputdir = xenrt.TEC().lookup("PRODUCT_INPUTDIR_%s" % (self.INITIAL_VERSION.replace(" ", "").upper()), None)
        if not inputdir:
            inputdir = xenrt.TEC().lookup("PIDIR_%s" % (self.INITIAL_VERSION.replace(" ", "").upper()), None)
        if not inputdir:
            raise xenrt.XRTError("No product input directory set for %s" % (self.INITIAL_VERSION))

        if self.CC:
            sku = False
        else:
            sku = self.LICENSESKU
            usev6 = xenrt.TEC().lookup(["VERSION_CONFIG", self.INITIAL_VERSION, "V6_DBV"], None)
            if usev6:
                sku = False

        productVersion = self.INITIAL_VERSION.split()[0]
        self.host = xenrt.lib.xenserver.createHost(version=inputdir, productVersion=productVersion, license=sku)
        self.getLogsFrom(self.host)
        
        if self.CC:
            self.host.configureForCC()
            
            # Create a shared SR for the license server as there's no local SR for CC
            nfsSR = xenrt.lib.xenserver.NFSStorageRepository(self.host, "nfs")
            nfsSR.create()
            self.host.addSR(nfsSR, default=True)
        
        if self.POOLED:
            self.slave = xenrt.lib.xenserver.createHost(id=1, version=inputdir, productVersion=productVersion, license=sku)
            
            if self.CC:
                self.slave.configureForCC()
            
            self.getLogsFrom(self.slave)
        
        self.currentversion = productVersion
        xenrt.TEC().comment("Initial host(s) install of %s" % self.INITIAL_VERSION)
        v6applied = False
        if not self.CC and usev6:
            xenrt.resources.SharedHost().getHost().installLicenseServerGuest(name="LicenseServer",host=self.host)
            
            v6 = self.getGuest("LicenseServer").getV6LicenseServer()
            self.uninstallOnCleanup(self.getGuest("LicenseServer"))
            v6.removeAllLicenses()
            self.host.applyFullLicense(v6)
            if self.POOLED:
                v6.removeAllLicenses()
                self.slave.applyFullLicense(v6)
            v6applied = True

        if self.POOLED:
            self.pool = xenrt.lib.xenserver.poolFactory(self.host.productVersion)(self.host)
            
            if self.CC:
                self.pool.configureSSL()
            
            self.pool.addHost(self.slave)
            
            # DL: add this when hotfix arrives
            # try mpp-rdac for Cowley onwards
            #if isinstance(self.pool, xenrt.lib.xenserver.MNRPool) and not "MNR" in self.INITIAL_VERSION:
            #    for h in self.pool.getHosts():
            #        h.enableMultipathing(mpp_rdac=True)

        if self.CHECKVM:
            # Install a VM
            self.guest = self.host.createGenericLinuxGuest()
            self.guest.shutdown()


        initialBranch = self.INITIAL_BRANCH
        if not initialBranch:
            initialBranch = xenrt.TEC().lookup(["DEFAULT_HOTFIX_BRANCH", self.INITIAL_VERSION],
                                xenrt.TEC().lookup(["HOTFIXES", self.INITIAL_VERSION]).keys()[0])

        # Perform hotfixes
        self.doHotfixes(self.INITIAL_VERSION, initialBranch, self.INITIAL_HOTFIXES)

        # Perform the required upgrades and hotfixes to those upgrades
        for i in range(len(self.UPGRADE_VERSIONS)):
            uver = self.UPGRADE_VERSIONS[i]
            try:
                ubranch = self.UPGRADE_BRANCHES[i]
            except:
                ubranch = xenrt.TEC().lookup(["DEFAULT_HOTFIX_BRANCH", uver],
                            xenrt.TEC().lookup(["HOTFIXES", uver]).keys()[0])

            uhfs = self.UPGRADE_HOTFIXES[i]
            uv6 = xenrt.TEC().lookup(["VERSION_CONFIG", uver, "V6_DBV"], None)

            inputdir = xenrt.TEC().lookup("PRODUCT_INPUTDIR_%s" %(uver.replace(" ", "").upper()), None)
            if not inputdir:
                inputdir = xenrt.TEC().lookup("PIDIR_%s" % (uver.replace(" ", "").upper()), None)
            if not inputdir:
                raise xenrt.XRTError("No product input directory set for %s" % uver)
            xenrt.TEC().setInputDir(inputdir)

            try:
                # Perform the product upgrade
                if self.POOLED:
                    self.pool = self.pool.upgrade(uver)
                    self.host = self.pool.master
                    self.slave = self.pool.getSlaves()[0]
                else:
                    self.host = self.host.upgrade(uver)
                time.sleep(180)
                if self.POOLED:
                    self.pool.check()
                else:
                    self.host.check()
                self.currentversion = uver
                xenrt.TEC().comment("Upgraded host(s) to %s" % (uver))

                if uv6 and not v6applied and not self.CC:
                    # Apply a v6 platinum license to this host
                    v6 = self.getGuest("LicenseServerForNonV6").getV6LicenseServer(host=self.host)
                    v6.removeAllLicenses()
                    self.host.applyFullLicense(v6)
                    if self.POOLED:
                        v6.removeAllLicenses()
                        self.slave.applyFullLicense(v6)
                    v6applied = True

                # Perform hotfixes for this version
                self.doHotfixes(uver, ubranch, uhfs)
                
            finally:
                xenrt.TEC().setInputDir(None)

        # Perform any steps required after the preparation installs/upgrades
        self.postPrepare()
        
        # Perform any necessary precheck
        self.preCheck()

    def doHotfixRetail(self):
        # Perform the hotfix
        patch = xenrt.TEC().lookup("THIS_HOTFIX")
        patches = self.host.minimalList("patch-list")
        if self.NEGATIVE:
            try:
                if self.POOLED:
                    self.pool.applyPatch(xenrt.TEC().getFile(patch))
                else:
                    self.host.applyPatch(xenrt.TEC().getFile(patch), patchClean=True)
                    
            except xenrt.XRTFailure, e:
                if "required_version" in e.data and "6.2_vGPU_Tech_Preview" in e.data:
                    xenrt.TEC().logverbose("Patch apply failed as expected when 6.2_vGPU_Tech_Preview is already installed")
                elif "required_version" in e.data and not "Service Pack" in e.data:
                    if not "^" in e.data or not e.data.strip().endswith("$"):
                        raise xenrt.XRTFailure("Version regex not correctly anchored")
                    elif not "\\." in e.data and not "BUILD_NUMBER" in e.data:
                        raise xenrt.XRTFailure("Backslashes not correctly escaped in version regex.")
            else:
                raise xenrt.XRTFailure("Able to apply patch when it should not be allowed")
                
        else:
            
            if self.POOLED:
                cmd = "cat /etc/xensource/pool.conf"
                masterPoolConfBefore = self.host.execdom0(cmd)
                slavePoolConfigBefore = self.slave.execdom0(cmd)

                self.pool.applyPatch(xenrt.TEC().getFile(patch))
                
                if self.host.execdom0(cmd) != masterPoolConfBefore:
                    raise xenrt.XRTFailure("master /etc/xensource/pool.conf changed after hotfix application")
                
                if self.slave.execdom0(cmd) != slavePoolConfigBefore:
                    raise xenrt.XRTFailure("slave /etc/xensource/pool.conf changed after hotfix application")
            
            else:
                self.host.applyPatch(xenrt.TEC().getFile(patch), patchClean=True)
            patches2 = self.host.minimalList("patch-list")
            self.host.execdom0("xe patch-list")
            if len(patches2) <= len(patches):
                raise xenrt.XRTFailure("Patch list did not grow after patch application")
            # Make sure all hosts have all patches
            for puuid in patches:
                hosts = self.host.genParamGet("patch", puuid, "hosts").split(", ")
                if not self.host.getMyHostUUID() in hosts:
                    raise xenrt.XRTFailure("Patch %s not applied to the master" % puuid)
                if self.POOLED and not self.slave.getMyHostUUID() in hosts:
                    raise xenrt.XRTFailure("Patch %s not applied to the slave" % puuid)

    def doHotfix(self):
        self.doHotfixRetail()

    def checkHotfixContents(self):
        if isinstance(self.host, xenrt.lib.xenserver.BostonHost):
            remotefn = "/tmp/XSUPDATE"
            sftp = self.host.sftpClient()
            hotfix = xenrt.TEC().lookup("THIS_HOTFIX")
 
            try:
                sftp.copyTo(xenrt.TEC().getFile(hotfix), remotefn)
            finally:
                sftp.close()

            if hotfix.endswith(".unsigned"):
                ret = self.host.execdom0("bash %s unpack" % remotefn).strip()
            else:
                # decrypt hotfix
                self.host.execdom0("gpg --keyring /opt/xensource/gpg/pubring.gpg -d %s > %s.sh" % (remotefn, remotefn))
                
                # unpack hotfix contents
                ret = self.host.execdom0("bash %s.sh unpack" % remotefn).strip()
            
            # view hotfix contents
            contents = self.host.execdom0("cat %s/CONTENTS | sort" % ret).strip()
            contentsUniq = self.host.execdom0("cat %s/CONTENTS | sort | uniq" % ret).strip()
            
            if contents != contentsUniq:
                raise xenrt.XRTFailure("Duplicated lines in hotfix contents")

    
    def checkDriverDisks(self):
        
        if not xenrt.TEC().lookup("DRIVER_DISK_REPO", None):
            return
        
        step("Fetch DriverDisk repo")
        td = xenrt.TEC().tempDir()
        if "driverdisks.hg" in xenrt.TEC().lookup("DRIVER_DISK_REPO"):
            xenrt.util.command("cd %s && hg clone %s driverDisk" % (td, xenrt.TEC().lookup("DRIVER_DISK_REPO")))
        else:
            xenrt.util.command("wget -r --no-parent --reject 'index.html*' %s -P %s/driverDisk" % (xenrt.TEC().lookup("DRIVER_DISK_REPO"), td))
            #extract zip files
            xenrt.util.command("cd %s && find ./ -name *.zip -exec sh -c 'unzip -d `dirname {}` {}' ';'" % td)
        # remove all but iso
        xenrt.util.command("cd %s && find -type f | grep -v .iso | xargs rm -f " % td)
        # tar the content, copy to the host and untar
        xenrt.util.command("cd %s && tar -czf driverdisks.tgz driverDisk" % (td))
        step("Copy the driver disks content to host")
        sftp = self.host.sftpClient()
        try: 
            sftp.copyTo("%s/driverdisks.tgz" % td, "/driverdisks.tgz")
        finally:
            sftp.close()
        self.host.execdom0("cd / && tar -xzf driverdisks.tgz && rm /driverdisks.tgz")

        step("Listing driver disks for this kernel")
        if isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            isos = self.host.execdom0('cd / && find /driverDisk | grep ".iso$" || true').strip().splitlines()
        else:
            self.host.execdom0("uname -r")
            isos = self.host.execdom0('cd / && find /driverDisk | grep "`uname -r`" | grep ".iso$" || true').strip().splitlines()
        
        step("Performing tests for all the driver disks")
        for i in range(len(isos)):
            step("Testing %s" % (isos[i]))
            
            log("mount the driver disk")
            self.host.execdom0("mkdir /mnt/%d" % i)
            self.host.execdom0("mount -o loop %s /mnt/%d" % (isos[i], i))
            
            # create a location to copy contents of driver disk to.
            # we do this as we need read-write access to hack the install.sh script
            self.host.execdom0("mkdir /tmp/%d" % i)
            
            # copy driver disk contents to /tmp/{i}
            self.host.execdom0("cp -R /mnt/%d/* /tmp/%d/" % (i, i))

            # unmount driver disk
            self.host.execdom0("cd / && umount /mnt/%d && rmdir /mnt/%d" % (i, i))
            
            # hack driver disk scripts so doesn't ask to confirm
            self.host.execdom0("sed -i 's/if \[ -d \$installed_repos_dir\/$identifier \]/if \[ 0 -eq 1 \]/' /tmp/%d/install.sh" % i)
            self.host.execdom0('sed -i "s/print msg/return/" /tmp/%d/install.sh || true' % i)
            
            log("List rpms in driver disk")
            xenrt.TEC().logverbose("Listing RPMs in driver disk")
            driverDiskRpms = self.host.execdom0('cd / && find /tmp/%d | grep ".rpm$"' % i).strip().splitlines()
            
            # dictionary of kernel objects for cross referencing against installed ones after driver disk has been installed
            kos = {}
            
            log("Manually unpack all rpms to get driver names and versions")
            xenrt.TEC().logverbose("Unpacking all RPMs in driver disk so can get version numbers")
            for j in range(len(driverDiskRpms)):
                self.host.execdom0("mkdir /tmp/%d/%d" % (i, j))
                self.host.execdom0("cd /tmp/%d/%d && rpm2cpio %s | cpio -idmv" % (i, j, driverDiskRpms[j]))
                
                for ko in self.host.execdom0('cd / && find /tmp/%d/%d | grep ".ko$" || true' % (i, j)).strip().splitlines():
                    koShort = re.match(".*/(.*?)\.ko$", ko).group(1)
                    if not koShort in kos or 'xen' in ko:
                        kos[koShort] = self.host.execdom0('modinfo %s | grep "^srcversion:"' % ko)

            # list all rpms before installing driver disk
            rpmsBefore = self.host.execdom0("rpm -qa|sort").splitlines()
        
            log("Install the driver disk")
            self.host.execdom0("cd /tmp/%d && ./install.sh" % i)
            
            log("Ensure the module dependency table has been updated correctly")
            for ko in kos:
                if len(self.host.execdom0("modinfo %s | grep `uname -r`" % ko).strip().splitlines()) == 0:
                    raise xenrt.XRTFailure("Could not find kernel version in driver modinfo for %s" % ko)
                    
                if kos[ko] != self.host.execdom0('modinfo %s | grep "^srcversion:"' % ko):
                    raise xenrt.XRTFailure("driver modinfo shows incorrect version. It should be \"%s\"." % kos[ko])

            self.writeToUsrGroups(isos[i].replace("/driverdisks.hg/", "").replace("/", "-").replace(".iso", ""))
            
            # list all rpms after installing driver disk
            rpmsAfter = self.host.execdom0("rpm -qa|sort").splitlines()
            
            # get list of all new rpms installed (according to the system)
            log("Get the list of new rpms after installation")
            newRpms = filter(lambda x: not x in rpmsBefore, rpmsAfter)
            xenrt.TEC().logverbose("New RPMS:\n" + "\n".join(newRpms))
            
             # now uninstall (this helps when you have multiple versions of the same driver)
            log("Uninstall the driver disk: remove rpms")
            uniqueNewRpms =  []
            for rpm in newRpms:
                try:
                    self.host.execdom0("rpm -ev %s" % rpm)
                    uniqueNewRpms.append(rpm)
                except Exception, e:
                    if "Failed dependencies" in e.data:
                        newRpms.append(rpm)
                    else:
                        raise
                    
            log("Check the number of rpms installed is as expected")
            if len(uniqueNewRpms) != len(driverDiskRpms):
                raise xenrt.XRTFailure("Incorrect RPMs installed by driver disk. Expected %d. Found %d." % (len(driverDiskRpms), len(uniqueNewRpms)))

            # remove repository stamp from xapi database
            try:
                command = """cd /tmp/%d &&  python -c "from xcp.accessor import *; from xcp.repository import *; print Repository(FileAccessor('file://./', True), '').identifier" """ % i
                repoID = self.host.execdom0(command).strip()
                self.host.execdom0("rm -rf /etc/xensource/installed-repos/%s" % repoID)
            except:
                pass

    def checkPatchList(self):
        # Make sure the patch list contains everything we expected and no
        # more. If an expected patch description contains "*" then any
        # hotfix can match this - this is used for testing new hotfixes
        # where the name is not specified as needing testing.
        exps = xenrt.TEC().lookupLeaves("PATCH_DESCRIPTIONS")
        hftexts = []        
        for puuid in self.host.minimalList("patch-list"):
            hftext = self.host.genParamGet("patch", puuid, "name-label")
            hftexts.append(hftext)
        missing = []
        any = 0
        for exp in exps:
            if exp == "*":
                any = any + 1
            else:
                if exp in hftexts:
                    hftexts.remove(exp)
                else:
                    missing.append(exp)
        if any and len(hftexts) == any:
            # The number of hotfix names we have after removing the expected
            # ones matches the number of wildcards - this is good.
            hftexts = []
        
        
        # Commenting this out for now. It's good practice to check
        # apply the hotfix and check this manually and it's annoying
        # if this fails.
        #if len(missing) > 0:
        #    raise xenrt.XRTFailure("Patch(es) missing: %s" %
        #                           (string.join(missing, ",")))
        #if len(hftexts) > 0:
        #    raise xenrt.XRTFailure("Unexpected patch(es): %s" %
        #                           (string.join(hftexts, ",")))
        
    def checkGuest(self):
        # Check the VM
        self.guest.start()
        self.guest.shutdown()

    def checkNTP(self, master):
        if master:
            host = self.host
        else:
            host = self.slave
        # Make sure /etc/ntp.conf exists or is a symlink to a file that
        # exists
        if host.execdom0("test -e /etc/ntp.conf", retval="code") != 0:
            if host.execdom0("test -L /etc/ntp.conf", retval="code") == 0:
                raise xenrt.XRTFailure("/etc/ntp.conf is a dangling symlink")
            else:
                raise xenrt.XRTFailure("/etc/ntp.conf is missing")

        # Make sure the ntpd service is reported as running
        data = host.execdom0("service ntpd status | cat")
        if not "running" in data:
            raise xenrt.XRTFailure("ntpd service is not running")

        # Make sure the ntpd process is running
        data = host.execdom0("ps axw")
        if not "ntpd" in data:
            raise xenrt.XRTFailure("ntpd process is not running")
        
    def run(self, arglist):

        self.runSubcase("checkHotfixContents", (), "Check", "Hotfix")
        
        # Apply the hotfix but don't reboot yet
        if self.runSubcase("doHotfix", (), "Patch", "Apply") != xenrt.RESULT_PASS:
            return
        
        if not self.NEGATIVE:
            self.runSubcase("checkPatchList", (), "PatchList", "Initial")

        # Reboot into the patched installation
        self.host.reboot()
        if self.POOLED:
            self.slave.reboot()

        if not self.POOLED and not self.NEGATIVE:
            self.runSubcase("checkDriverDisks", (), "Check", "DriverDisks")
            
        if not self.NEGATIVE:
            # Check the list again
            if self.runSubcase("checkPatchList", (), "PatchList", "Reboot") != xenrt.RESULT_PASS:
                return

        if self.CHECKVM:
            # Make sure our VM still works/exists
            if self.runSubcase("checkGuest", (), "Check", "VM") != xenrt.RESULT_PASS:
                return

        if not self.NEGATIVE:
            # Reboot and check the list again
            self.host.reboot()
            if self.POOLED:
                self.slave.reboot()
            if self.runSubcase("checkPatchList", (), "PatchList", "Reboot2") != xenrt.RESULT_PASS:
                return

        self.runSubcase("checkNTP", (True), "CA-27444", "master")
        if self.POOLED:
            self.runSubcase("checkNTP", (False), "CA-27444", "slave")

        for e in self.EXTRASUBCASES:
            if self.runSubcase(e[0], e[1], e[2], e[3]) != xenrt.RESULT_PASS:
                return

#############################################################################
# Hotfix application

# Base versions
class _MiamiRTM(_Hotfix):
    INITIAL_VERSION = "Miami"
    
class _MiamiHF3(_MiamiRTM):
    INITIAL_HOTFIXES = ["HF1", "HF2", "HF3"]

class _OrlandoRTM(_Hotfix):
    INITIAL_VERSION = "Orlando"

class _OrlandoHF1(_OrlandoRTM):
    INITIAL_HOTFIXES = ["HF1"]
    
class _OrlandoHF2(_OrlandoRTM):
    INITIAL_HOTFIXES = ["HF1", "HF2"]
    
class _OrlandoHF3(_OrlandoRTM):
    INITIAL_HOTFIXES = ["HF1", "HF2", "HF3"]
    
class _OrlandoHF2only(_OrlandoRTM):
    INITIAL_HOTFIXES = ["HF2"]

class _OrlandoHF3only(_OrlandoRTM):
    INITIAL_HOTFIXES = ["HF3"]
    
class _OrlandoAllHFonly(_OrlandoRTM):
    INITIAL_HOTFIXES = ["HF3", "XS50EU3004", "XS50EU3005", "XS50EU3007", "XS50EU3008", "XS50EU3009", "XS50EU3010", "XS50EU3011", "XS50EU3012", "XS50EU3013", "XS50EU3014", "XS50EU3015", "XS50EU3016", "XS50EU3017", "XS50EU3018"]

class _FloodgateRTM(_Hotfix):
    INITIAL_VERSION = "Orlando HF3"
    INITIAL_BRANCH = "RTM"

class _GeorgeRTM(_Hotfix):
    INITIAL_VERSION = "George"

class _GeorgeHFd(_GeorgeRTM):
    INITIAL_HOTFIXES = ["LVHD","EPT","Time"]

class _GeorgeHF1(_GeorgeRTM):
    INITIAL_HOTFIXES = ["HF1"]

class _GeorgeHF2(_GeorgeRTM):
    INITIAL_HOTFIXES = ["HF2"]

class _GeorgeU1(_Hotfix):
    INITIAL_VERSION = "George HF1"
    INITIAL_BRANCH = "RTM"

class _GeorgeU2(_Hotfix):
    INITIAL_VERSION = "George HF2"
    INITIAL_BRANCH = "RTM"
    
class _GeorgeU2HFd(_GeorgeRTM):
    INITIAL_HOTFIXES = ["HF1", "HF2", "XS55EU2004", "XS55EU2005", "XS55EU2006", "XS55EU2007", "XS55EU2008", "XS55EU2009", "XS55EU2010", "XS55EU2011", "XS55EU2012", "XS55EU2013", "XS55EU2014", "XS55EU2015", "XS55EU2016", "XS55EU2017", "XS55EU2018", "XS55EU2019", "XS55EU2020", "XS55EU2021", "XS55EU2022", "XS55EU2023", "XS55EU2024", "XS55EU2025", "XS55EU2026"]

class _MNRRTM(_Hotfix):
    INITIAL_VERSION = "MNR"

class _MNRHFd(_MNRRTM):
    INITIAL_HOTFIXES = ["XS56E001", "XS56E002", "XS56E003", "XS56E004", "XS56E005", "XS56E006", "XS56E007", "XS56E009", "XS56E010", "XS56E011", "XS56E012", "XS56E013", "XS56E014", "XS56E015", "XS56E016", "XS56E017", "XS56E018", "XS56E019", "XS56E020", "XS56E021", "XS56E022", "XS56E023"]

class _MNRCCRTM(_Hotfix):
    INITIAL_VERSION = "MNRCC"
    CC = True

class _MNRCCHFd(_MNRCCRTM):
    INITIAL_HOTFIXES = ["XS56ECC001", "XS56ECC002", "XS56ECC003", "XS56ECC004", "XS56ECC005", "XS56ECC006", "XS56ECC007", "XS56ECC008",  "XS56ECC009", "XS56ECC010", "XS56ECC011"]

class _CowleyRTM(_Hotfix):
    INITIAL_VERSION = "Cowley"
    
class _CowleyWithOxford(_CowleyRTM):
    INITIAL_HOTFIXES = ["HFOXFORD"]

class _CowleyHFd(_CowleyRTM):
    INITIAL_HOTFIXES = ["XS56EFP1001", "XS56EFP1004", "XS56EFP1005", "XS56EFP1006", "XS56EFP1007", "XS56EFP1008", "XS56EFP1009", "XS56EFP1010", "XS56EFP1011" , "XS56EFP1012", "XS56EFP1013", "XS56EFP1014", "XS56EFP1015", "XS56EFP1016", "XS56EFP1017",  "XS56EFP1018", "XS56EFP1019", "XS56EFP1020", "XS56EFP1021", "XS56EFP1022"]
    
class _CowleyWithOxfordAndBob(_CowleyRTM):
    INITIAL_HOTFIXES = ["HFOXFORD","HFBOB"]

class _OxfordRTM(_Hotfix):
    INITIAL_VERSION = "Oxford"
    
class _OxfordHFd(_OxfordRTM):
    INITIAL_HOTFIXES = ["XS56ESP2001", "XS56ESP2002", "XS56ESP2003", "XS56ESP2004", "XS56ESP2005", "XS56ESP2006", "XS56ESP2007", "XS56ESP2008", "XS56ESP2009", "XS56ESP2010", "XS56ESP2011", "XS56ESP2012", "XS56ESP2013", "XS56ESP2014", "XS56ESP2015", "XS56ESP2016", "XS56ESP2018", "XS56ESP2019", "XS56ESP2020", "XS56ESP2021", "XS56ESP2022", "XS56ESP2023", "XS56ESP2024", "XS56ESP2025", "XS56ESP2026", "XS56ESP2027", "XS56ESP2028", "XS56ESP2029", "XS56ESP2030", "XS56ESP2031", "XS56ESP2032", "XS56ESP2033", "XS56ESP2034"]
    
class _BostonRTM(_Hotfix):
    INITIAL_VERSION = "Boston"
    
class _BostonBritney(_BostonRTM):
    INITIAL_HOTFIXES = ["XS60E001"]

class _BostonHFd(_BostonRTM):
    INITIAL_HOTFIXES = ["XS60E001", "XS60E002", "XS60E003", "XS60E004", "XS60E005", "XS60E006", "XS60E007", "XS60E008", "XS60E010", "XS60E012", "XS60E013", "XS60E014", "XS60E015", "XS60E016", "XS60E017", "XS60E018", "XS60E019", "XS60E020", "XS60E021", "XS60E022", "XS60E023", "XS60E024", "XS60E025", "XS60E026", "XS60E027", "XS60E028", "XS60E029", "XS60E030", "XS60E031", "XS60E032", "XS60E033", "XS60E034", "XS60E035", "XS60E036","XS60E037","XS60E038", "XS60E039","XS60E040", "XS60E041", "XS60E042", "XS60E043", "XS60E045", "XS60E046", "XS60E047", "XS60E048", "XS60E049", "XS60E050", "XS60E051", "XS60E052", "XS60E053"]

class _SanibelRTM(_Hotfix):
    INITIAL_VERSION = "Sanibel"
    
class _SanibelHFd(_SanibelRTM):
    INITIAL_HOTFIXES = ["XS602E004", "XS602E005", "XS602E006", "XS602E007", "XS602E008", "XS602E009", "XS602E010", "XS602E011", "XS602E013", "XS602E014", "XS602E016", "XS602E017", "XS602E018", "XS602E019", "XS602E020", "XS602E021", "XS602E022", "XS602E023", "XS602E024", "XS602E025", "XS602E026", "XS602E027", "XS602E028", "XS602E029", "XS602E030", "XS602E031", "XS602E032", "XS602E033", "XS602E034", "XS602E035", "XS602E036", "XS602E037", "XS602E038", "XS602E039", "XS602E041", "XS602E042", "XS602E043","XS602E044","XS602E045","XS602E046","XS602E047", "XS602E048"]
    
class _SanibelCCRTM(_Hotfix):
    INITIAL_VERSION = "SanibelCC"
    CC = True
    
class _SanibelCCHFd(_SanibelCCRTM):
    INITIAL_HOTFIXES = ["XS602ECC001", "XS602ECC002", "XS602ECC003", "XS602ECC004", "XS602ECC005", "XS602ECC006", "XS602ECC007", "XS602ECC008", "XS602ECC009", "XS602ECC010", "XS602ECC011", "XS602ECC012", "XS602ECC013", "XS602ECC014", "XS602ECC015", "XS602ECC017", "XS602ECC018", "XS602ECC019","XS602ECC020","XS602ECC021","XS602ECC022","XS602ECC023", "XS602ECC024"]

class _TampaRTM(_Hotfix):
    INITIAL_VERSION = "Tampa"
    
class _TampaHFd(_TampaRTM):
    INITIAL_HOTFIXES = ["XS61E001", "XS61E003", "XS61E004", "XS61E008", "XS61E009", "XS61E010", "XS61E013", "XS61E015", "XS61E017",  "XS61E018", "XS61E019", "XS61E020", "XS61E021", "XS61E022", "XS61E023", "XS61E024", "XS61E025", "XS61E026", "XS61E027", "XS61E028", "XS61E029", "XS61E030", "XS61E032", "XS61E033", "XS61E034", "XS61E035", "XS61E036", "XS61E037", "XS61E038", "XS61E039", "XS61E040", "XS61E041", "XS61E042", "XS61E043", "XS61E044", "XS61E045", "XS61E046", "XS61E047", "XS61E048", "XS61E050", "XS61E051", "XS61E052","XS61E053","XS61E054","XS61E055","XS61E056","XS61E057","XS61E058","XS61E059", "XS61E060"]
    
class _ClearwaterRTM(_Hotfix):
    INITIAL_VERSION = "Clearwater"
    INITIAL_BRANCH = "RTM"
    
class _ClearwaterRTMHFd(_ClearwaterRTM):
    INITIAL_HOTFIXES = ["XS62E001", "XS62E002", "XS62E004", "XS62E005", "XS62E007", "XS62E008", "XS62E009", "XS62E010", "XS62E011", "XS62E012", "XS62E014", "XS62E015", "XS62E016", "XS62E017"]
    
class _ClearwaterSP1(_ClearwaterRTM):
    INITIAL_BRANCH = "SP1"
    INITIAL_HOTFIXES = ["XS62ESP1"]
    
class _ClearwaterSP1HFd(_ClearwaterSP1):
    INITIAL_HOTFIXES = ["XS62ESP1", "XS62ESP1002", "XS62ESP1003", "XS62ESP1004", "XS62ESP1005", "XS62ESP1006", "XS62ESP1007", "XS62ESP1008", "XS62ESP1009", "XS62ESP1011", "XS62ESP1012", "XS62ESP1013", "XS62ESP1014", "XS62ESP1015", "XS62ESP1016", "XS62ESP1017", "XS62ESP1019", "XS62ESP1020", "XS62ESP1021", "XS62ESP1024", "XS62ESP1025", "XS62ESP1026","XS62ESP1027","XS62ESP1028","XS62ESP1030","XS62ESP1031","XS62ESP1032","XS62ESP1033", "XS62ESP1034"]
    
class _CreedenceRTM(_Hotfix):
    INITIAL_VERSION = "Creedence"
    INITIAL_BRANCH = "RTM"
    
class _CreedenceRTMHFd(_CreedenceRTM):
    INITIAL_HOTFIXES = ["XS65E001", "XS65E002", "XS65E003", "XS65E005", "XS65E006", "XS65E007", "XS65E008", "XS65E009","XS65E010","XS65E011","XS65E013","XS65E014","XS65E015", "XS65E016", "XS65E017"]
    
class _CreedenceSP1(_CreedenceRTM):
    INITIAL_BRANCH = "SP1"
    INITIAL_HOTFIXES = ["XS65ESP1"]
    
class _CreedenceSP1HFd(_CreedenceSP1):
    INITIAL_HOTFIXES = ["XS65ESP1","XS65ESP1002","XS65ESP1003","XS65ESP1004","XS65ESP1005","XS65ESP1008","XS65ESP1009","XS65ESP1010","XS65ESP1011","XS65ESP1012","XS65ESP1013","XS65ESP1014", "XS65ESP1016"]
    
    
# Upgrades
class _OrlandoRTMviaMiamiHF3(_MiamiHF3):
    UPGRADE_VERSIONS = ["Orlando"]
    UPGRADE_HOTFIXES = [[]]

class _OrlandoHF1viaMiamiHF3(_OrlandoRTMviaMiamiHF3):
    UPGRADE_HOTFIXES = [["HF1"]]

class _OrlandoHF2viaMiamiHF3(_OrlandoRTMviaMiamiHF3):
    UPGRADE_HOTFIXES = [["HF2"]]

class _OrlandoHF3viaMiamiHF3(_OrlandoRTMviaMiamiHF3):
    UPGRADE_HOTFIXES = [["HF3"]]

# Single host testcases
class TC8821(_OrlandoRTM):
    """Apply hotfix to XenServer 5.0.0 RTM"""
    pass

class TC8822(_OrlandoHF1):
    """Apply hotfix to XenServer 5.0.0 update 1"""
    pass

class TC8823(_OrlandoHF2only):
    """Apply hotfix to XenServer 5.0.0 update 2"""
    pass

class TC8824(_OrlandoHF2):
    """Apply hotfix to XenServer 5.0.0 update 1 + update 2"""
    pass

class TC8825(_OrlandoRTMviaMiamiHF3):
    """Apply hotfix to XenServer 5.0.0 RTM which has been upgraded from Miami + Miami updates 1, 2 and 3"""
    pass

class TC10539(_OrlandoHF3only):
    """Apply hotfix to XenServer 5.0.0 update 3"""
    pass
    
class TC17913(_OrlandoAllHFonly):
    """Apply hotfix to XenServer 5.0.0 update 3 and all other hotfixes"""
    pass
    
class TC10540(_OrlandoHF3):
    """Apply hotfix to XenServer 5.0.0 update 1 + update 2 + update 3"""
    pass

class TC10541(_FloodgateRTM):
    """Apply hotfix to XenServer 5.0.0u3 (Floodgate rollup) RTM"""
    pass

class TC10603(_GeorgeRTM):
    """Apply hotfix to XenServer 5.5.0 RTM"""
    pass

class TC10604(_GeorgeHFd):
    """Apply hotfix to XenServer 5.5.0 + LVHD, EPT, and time hotfixes"""
    pass

class TC10777(_GeorgeHF1):
    """Apply hotfix to XenServer 5.5.0 + update 1 hotfix"""
    pass

class TC11501(_GeorgeHF2):
    """Apply hotfix to XenServer 5.5.0 + update 2 hotfix"""
    pass

class TC10798(_GeorgeU1):
    """Apply hotfix to XenServer 5.5.0 Update 1"""
    pass

class TC11502(_GeorgeU2):
    """Apply hotfix to XenServer 5.5.0 Update 2"""
    pass

class TC17964(_GeorgeU2HFd):
    """Apply hotfix to XenServer 5.5.0 Update 2 and all other hotfixes"""
    pass

class TC11934(_MNRRTM):
    """Apply hotfix to XenServer 5.6.0 RTM"""
    pass

class TC11940(_MNRHFd):
    """Apply hotfix to XenServer 5.6.0 RTM with all previous released hotfixes applied"""
    pass

class TC17970(_MNRCCRTM):
    """Apply hotfix to XenServer 5.6.0 RTM"""
    pass

class TC17971(_MNRCCHFd):
    """Apply hotfix to XenServer 5.6.0 RTM with all previous released hotfixes applied"""
    pass

class TC12694(_CowleyRTM):
    """Apply hotfix to XenServer 5.6 FP1 RTM"""
    pass
    
class TC14455(_CowleyWithOxford):
    """Apply hotfix to XenServer 5.6 FP1 RTM + SP2 Hotfix"""
    pass
    
class TC14908(_CowleyWithOxfordAndBob):
    """Apply hotfix to XenServer 5.6 FP1 RTM + SP2 Hotfix + Bob Hotfix"""
    pass

class TC15521(_CowleyHFd):
    """Apply hotfix to XenServer 5.6.0 FP1 RTM with all previous released hotfixes applied"""
    pass

class TC14439(_OxfordRTM):
    """Apply hotfix to XenServer 5.6 SP2 RTM"""
    pass
    
class TC15238(_OxfordHFd):
    """Apply hotfix to XenServer 5.6 SP2 RTM with all previous hotfixes applied"""
    pass
    
class TC15215(_BostonRTM):
    """Apply hotfix to XenServer 6.0.0 RTM"""
    pass
    
class TC16628(_SanibelRTM):
    """Apply hotfix to XenServer 6.0.2 RTM"""
    pass
    
class TC18394(_SanibelCCRTM):
    """Apply hotfix to XenServer 6.0.2 CC RTM"""
    pass

class TC18162(_TampaRTM):
    """Apply hotfix to XenServer 6.1 RTM"""
    pass

class TC19911(_ClearwaterRTM):
    """Apply hotfix to XenServer 6.2 RTM"""
    pass

class TC20944(_ClearwaterSP1):
    """Apply hotfix to XenServer 6.2 SP1"""
    pass

class TC15307(_BostonBritney):
    """Apply hotfix to XenServer 6.0.0 with Hotfix Britney applied"""
    pass

class TC15218(_BostonHFd):
    """Apply hotfix to XenServer 6.0 RTM with all previous released hotfixes applied"""
    pass
    
class TC16630(_SanibelHFd):
    """Apply hotfix to XenServer 6.0.2 RTM with all previous released hotfixes applied"""
    pass
    
class TC18395(_SanibelCCHFd):
    """Apply hotfix to XenServer 6.0.2 CC RTM with all previous released hotfixes applied"""
    pass
    
class TC18171(_TampaHFd):
    """Apply hotfix to XenServer 6.0.2 RTM with all previous released hotfixes applied"""
    pass

class TC19915(_ClearwaterRTMHFd):
    """Apply hotfix to XenServer 6.2 RTM with all previous released (non-SP1) hotfixes applied"""
    pass

class TC20927(_ClearwaterSP1HFd):
    """Apply hotfix to XenServer 6.2 SP1 with all previous released hotfixes applied"""
    pass
    
class TC23786(_CreedenceRTMHFd):
    """Apply hotfix to XenServer 6.5 RTM with all previous released (non-SP1) hotfixes applied"""
    pass
    
class TC27009(_CreedenceSP1HFd):
    """Apply hotfix to XenServer 6.5 SP1 with all previous released (SP1) hotfixes applied"""
    pass
    
# Negative tests (the hotfix should not apply to this base)
class TC10545(_OrlandoRTM):
    """Apply hotfix to XenServer 5.0.0 RTM (should fail)"""
    NEGATIVE = True

class TC10546(_OrlandoHF1):
    """Apply hotfix to XenServer 5.0.0 + update 1 (should fail)"""
    NEGATIVE = True

class TC10547(_OrlandoHF2only):
    """Apply hotfix to XenServer 5.0.0 + update 2 (should fail)"""
    NEGATIVE = True

class TC10723(_FloodgateRTM):
    """Apply hotfix to XenServer 5.0.0u3 (Floodgate rollup) RTM (should fail)"""
    NEGATIVE = True

class TC10605(_GeorgeU1):
    """Apply hotfix to XenServer 5.5.0 Update 1 (should fail)"""
    NEGATIVE = True

class TC11505(_GeorgeHF1):
    """Apply hotfix to XenServer 5.5.0 + update 1 (should fail)"""
    NEGATIVE = True

class TC11506(_GeorgeRTM):
    """Apply hotfix to XenServer 5.5.0 RTM (should fail)"""
    NEGATIVE = True

class TC11507(_GeorgeHFd):
    """Apply hotfix to XenServer 5.5.0 + LVHD, EPT, and time hotfixes (should fail)"""
    NEGATIVE = True

class TC11936(_GeorgeU2):
    """Apply hotfix to XenServer 5.5.0 Update 2 (should fail)"""
    NEGATIVE = True
    
class TC12695(_MNRRTM):
    """Apply hotfix to XenServer 5.6.0 (should fail)"""
    NEGATIVE = True

class TC14438(_CowleyRTM):
    """Apply hotfix to XenServer 5.6 FP1 (should fail)"""
    NEGATIVE = True
    
class TC15522(_CowleyWithOxford):
    """Apply hotfix to XenServer 5.6 FP1 RTM + SP2 Hotfix (should fail)"""
    NEGATIVE = True

class TC15216(_OxfordRTM):
    """Apply hotfix to XenServer 5.6 FP1 SP2 (should fail)"""
    NEGATIVE = True

class TC15306(_BostonRTM):
    """Apply hotfix to XenServer 6.0 (should fail)"""
    NEGATIVE = True
    
class TC18488(_SanibelCCRTM):
    """Apply hotfix to XenServer 6.0.2 CC (should fail)"""
    NEGATIVE = True

class TC16632(_SanibelRTM):
    """Apply hotfix to XenServer 6.0.2 (should fail)"""
    NEGATIVE = True
    
class TC19912(_TampaRTM):
    """Apply hotfix to XenServer 6.2 (should fail)"""
    NEGATIVE = True
    
class TC20945(_ClearwaterRTM):
    """Apply hotfix to XenServer 6.2RTM (should fail)"""
    NEGATIVE = True

class TC23783(_ClearwaterRTM):
    """Apply hotfix to XenServer 6.2 (should fail)"""
    NEGATIVE = True
    
class TC23785(_ClearwaterSP1):
    """Apply hotfix to XenServer 6.2 SP1(should fail)"""
    NEGATIVE = True
    
class TC27005(_CreedenceRTM):
    """Apply hotfix to XenServer 6.5(should fail)"""
    NEGATIVE = True

class TC23784(_CreedenceRTM):
    """Apply XS 6.5 hotfix to XenServer 6.5 RTM"""
    pass

class TC27006(_CreedenceSP1):
    """Apply XS 6.5 SP1 hotfix to XenServer 6.5 SP1"""
    pass

class TC27007(_CreedenceSP1):
    """Apply hotfix to XenServer 6.5 SP1(should fail)"""
    NEGATIVE = True

class TCvGPUTechPreview(_ClearwaterRTM):
    """Apply hotfix to XenServer 6.2 RTM with vGPU Tech Preview installed"""
    NEGATIVE = True
    INITIAL_HOTFIXES = ["XS62ETP001"]
    
# Pool testcases
class TC8842(_OrlandoRTM):
    """Apply hotfix to XenServer 5.0.0 RTM (pool)"""
    POOLED = True

class TC8843(_OrlandoHF1):
    """Apply hotfix to XenServer 5.0.0 update 1 (pool)"""
    POOLED = True

class TC8844(_OrlandoHF2only):
    """Apply hotfix to XenServer 5.0.0 update 2 (pool)"""
    POOLED = True

class TC8845(_OrlandoHF2):
    """Apply hotfix to XenServer 5.0.0 update 1 + update 2 (pool)"""
    POOLED = True

class TC8846(_OrlandoRTMviaMiamiHF3):
    """Apply hotfix to XenServer 5.0.0 RTM which has been upgraded from Miami + Miami updates 1, 2 and 3 (pool)"""
    POOLED = True

class TC10542(_OrlandoHF3only):
    """Apply hotfix to XenServer 5.0.0 update 3 (pool)"""
    POOLED = True

class TC10543(_OrlandoHF3):
    """Apply hotfix to XenServer 5.0.0 update 1 + update 2 + update 3 (pool)"""
    POOLED = True

class TC10544(_FloodgateRTM):
    """Apply hotfix to XenServer 5.0.0u3 (Floodgate rollup) RTM (pool)"""
    POOLED = True

class TC10606(_GeorgeRTM):
    """Apply hotfix to XenServer 5.5.0 RTM (pool)"""
    POOLED = True

class TC10607(_GeorgeHFd):
    """Apply hotfix to XenServer 5.5.0 + LVHD, EPT, and time hotfixes (pool)"""
    POOLED = True   

class TC10779(_GeorgeHF1):
    """Apply hotfix to XenServer 5.5.0 + update 1 hotfix (pool)"""
    POOLED = True

class TC11504(_GeorgeHF2):
    """Apply hotfix to XenServer 5.5.0 + update 2 hotfix (pool)"""
    POOLED = True

class TC10799(_GeorgeU1):
    """Apply hotfix to XenServer 5.5.0 Update 1 (pool)"""
    POOLED = True

class TC11503(_GeorgeU2):
    """Apply hotfix to XenServer 5.5.0 Update 2 (pool)"""
    POOLED = True

class TC11935(_MNRRTM):
    """Apply hotfix to XenServer 5.6.0 RTM (pool)"""
    POOLED = True

class TC17972(_MNRCCRTM):
    """Apply hotfix to XenServer 5.6.0 CC (pool)"""
    POOLED = True

class TC12696(_CowleyRTM):
    """Apply hotfix to XenServer 5.6 FP1 RTM (pool)"""
    POOLED = True
    
class TC14437(_OxfordRTM):
    """Apply hotfix to XenServer 5.6 FP1 SP2 RTM (pool)"""
    POOLED = True
    
class TC15217(_BostonBritney):
    """Apply hotfix to XenServer 6.0.0 RTM with hotfix Britney applied (XS60E001) (pool)"""
    POOLED = True

class TC16629(_SanibelRTM):
    """Apply hotfix to XenServer 6.0.2 RTM (pool)"""
    POOLED = True

class TC18396(_SanibelCCRTM):
    """Apply hotfix to XenServer 6.0.2 CC RTM (pool)"""
    POOLED = True
    
class TC18161(_TampaRTM):
    """Apply hotfix to XenServer 6.1 RTM (pool)"""
    POOLED = True
    INITIAL_HOTFIXES = ["XS61E009"]

class TC19914(_ClearwaterRTM):
    """Apply hotfix to XenServer 6.2 RTM (pool)"""
    POOLED = True
    
class TC20946(_ClearwaterSP1):
    """Apply hotfix to XenServer 6.2 SP1 (pool)"""
    POOLED = True
    
class TC23787(_CreedenceRTM):
    """Apply XS 6.5 hotfix to XenServer 6.5 RTM (pool)"""
    POOLED = True

class TC27008(_CreedenceSP1):
    """Apply XS 6.5 SP1 hotfix to XenServer 6.5 SP1 (pool)"""
    POOLED = True
#############################################################################
# Upgrade with a rollup

class _UpgradeRollup(_Hotfix):
    """Base class for tests that perform a product upgrade using a build
    that has rolled up hotfixes."""

    def doUpgrade(self):
        # Perform the product upgrade
        if self.POOLED:
            self.pool = self.pool.upgrade()
            self.host = self.pool.master
            self.slave = self.pool.getSlaves()[0]
        else:
            self.host = self.host.upgrade()
        time.sleep(180)
        if self.POOLED:
            self.pool.check()
        else:
            self.host.check()

    def run(self, arglist):

        # Perform the upgrade, this will boot in to the upgraded and patched
        # host
        if self.runSubcase("doUpgrade", (), "Upgrade", "Perform") != \
                xenrt.RESULT_PASS:
            return
        
        # Check the patch list
        if self.runSubcase("checkPatchList", (), "PatchList", "Upgraded") != \
                xenrt.RESULT_PASS:
            return

        if self.CHECKVM:
            # Make sure our VM still works/exists
            if self.runSubcase("checkGuest", (), "Check", "VM") != \
                   xenrt.RESULT_PASS:
                return

        # Reboot and check the list again
        self.host.reboot()
        if self.POOLED:
            self.slave.reboot()
        if self.runSubcase("checkPatchList", (), "PatchList", "Reboot") != \
                xenrt.RESULT_PASS:
            return

        for e in self.EXTRASUBCASES:
            if self.runSubcase(e[0], e[1], e[2], e[3]) != xenrt.RESULT_PASS:
                return

class _UpgradeNotAllowed(_Hotfix):
    """Base class for tests that checks the upgrade is not allowed for one particular to another """

    def doUpgrade(self):
        # Perform the product upgrade
        try:
            if self.POOLED:
                self.pool = self.pool.upgrade()
                self.host = self.pool.master
                self.slave = self.pool.getSlaves()[0]
            else:
                self.host = self.host.upgrade()
        except: 
            pass
        else:
            raise xenrt.XRTError("Upgrade was successful when it was not expected to")

    def run(self, arglist):

        # Perform the upgrade and verifies that upgrade should be unsuccesful
        if self.runSubcase("doUpgrade", (), "Upgrade", "Perform") != \
                xenrt.RESULT_PASS:
            return

class _RioRTMFailUpg(_UpgradeNotAllowed):
    INITIAL_VERSION = "Rio"

class _MiamiRTMFailUpg(_UpgradeNotAllowed):
    INITIAL_VERSION = "Miami"

class _OrlandoRTMFailUpg(_UpgradeNotAllowed):
    INITIAL_VERSION = "Orlando"

class _GeorgeRTMFailUpg(_UpgradeNotAllowed):
    INITIAL_VERSION = "George"

# Base versions
class _MiamiRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Miami"

class _MiamiHF1Upg(_MiamiRTMUpg):
    INITIAL_HOTFIXES = ["HF1"]

class _MiamiHF2Upg(_MiamiRTMUpg):
    INITIAL_HOTFIXES = ["HF1", "HF2"]

class _MiamiHF3Upg(_MiamiRTMUpg):
    INITIAL_HOTFIXES = ["HF1", "HF2", "HF3"]

class _MiamiRTMViaRioUpg(_UpgradeRollup):
    INITIAL_VERSION = "Rio"
    UPGRADE_VERSIONS = ["Miami"]
    UPGRADE_HOTFIXES = [[]]

class _OrlandoRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Orlando"

class _OrlandoHF1Upg(_OrlandoRTMUpg):
    INITIAL_HOTFIXES = ["HF1"]

class _OrlandoHF2Upg(_OrlandoRTMUpg):
    INITIAL_HOTFIXES = ["HF1", "HF2"]

class _OrlandoHF3Upg(_OrlandoRTMUpg):
    INITIAL_HOTFIXES = ["HF1", "HF2", "HF3"]

class _OrlandoHF3onlyUpg(_OrlandoRTMUpg):
    INITIAL_HOTFIXES = ["HF3"]

class _OrlandoRTMViaMiamiUpg(_UpgradeRollup):
    INITIAL_VERSION = "Miami"
    UPGRADE_VERSIONS = ["Orlando"]
    UPGRADE_HOTFIXES = [[]]
    
class _OrlandoRTMViaRioAndMiamiUpg(_UpgradeRollup):
    INITIAL_VERSION = "Rio"
    UPGRADE_VERSIONS = ["Miami", "Orlando"]
    UPGRADE_HOTFIXES = [[], []]

class _GeorgeBetaUpg(_UpgradeRollup):
    INITIAL_VERSION = "George Beta"

class _GeorgeRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "George"

class _GeorgeHF1Upg(_GeorgeRTMUpg):
    INITIAL_HOTFIXES = ["HF1"]

class _GeorgeHF2Upg(_GeorgeRTMUpg):
    INITIAL_HOTFIXES = ["HF1", "HF2"]

class _GeorgeRTMViaOrlandoUpg(_UpgradeRollup):
    INITIAL_VERSION = "Orlando"
    UPGRADE_VERSIONS = ["George"]
    UPGRADE_HOTFIXES = [[]]

class _GeorgeRTMViaOrlandoAndMiamiUpg(_UpgradeRollup):
    INITIAL_VERSION = "Miami"
    UPGRADE_VERSIONS = ["Orlando", "George"]
    UPGRADE_HOTFIXES = [[], []]

class _GeorgeRTMViaOrlandoAndMiamiAndRioUpg(_UpgradeRollup):
    INITIAL_VERSION = "Rio"
    UPGRADE_VERSIONS = ["Miami", "Orlando", "George"]
    UPGRADE_HOTFIXES = [[], [], []]

class _MidnightRideBetaUpg(_UpgradeRollup):
    INITIAL_VERSION = "MNR Beta"

class _MNRRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "MNR"

class _MNRRTMViaGeorgeUpg(_UpgradeRollup):
    INITIAL_VERSION = "George"
    UPGRADE_VERSIONS = ["MNR"]
    UPGRADE_HOTFIXES = [[]]

class _MNRRTMViaGeorgeAndOrlandoUpg(_UpgradeRollup):
    INITIAL_VERSION = "Orlando"
    UPGRADE_VERSIONS = ["George", "MNR"]
    UPGRADE_HOTFIXES = [[], []]

class _MNRRTMViaGeorgeAndOrlandoAndMiamiUpg(_UpgradeRollup):
    INITIAL_VERSION = "Miami"
    UPGRADE_VERSIONS = ["Orlando", "George", "MNR"]
    UPGRADE_HOTFIXES = [[], [], []]

class _MNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg(_UpgradeRollup):
    INITIAL_VERSION = "Rio"
    UPGRADE_VERSIONS = ["Miami", "Orlando", "George", "MNR"]
    UPGRADE_HOTFIXES = [[], [], [], []]

class _CowleyViaMNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg(_UpgradeRollup):
    INITIAL_VERSION = "Rio"
    UPGRADE_VERSIONS = ["Miami","Orlando", "George", "MNR", "Cowley"]
    UPGRADE_HOTFIXES = [[], [], [], [], []]

class _CowleyViaMNRRTMViaGeorgeAndOrlandoAndMiami(_UpgradeRollup):
    INITIAL_VERSION = "Miami"
    UPGRADE_VERSIONS = ["Orlando", "George", "MNR", "Cowley"]
    UPGRADE_HOTFIXES = [[], [], [], []]

class _CowleyViaMNRRTMViaGeorgeAndOrlando(_UpgradeRollup):
    INITIAL_VERSION = "Orlando"
    UPGRADE_VERSIONS = ["George", "MNR", "Cowley"]
    UPGRADE_HOTFIXES = [[], [], []]

class _CowleyViaMNRRTMViaGeorge(_UpgradeRollup):
    INITIAL_VERSION = "George"
    UPGRADE_VERSIONS = ["MNR", "Cowley"]
    UPGRADE_HOTFIXES = [[], []]

class _CowleyViaMNRRTM(_UpgradeRollup):
    INITIAL_VERSION = "MNR"
    UPGRADE_VERSIONS = ["Cowley"]
    UPGRADE_HOTFIXES = [[]]

class _CowleyRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Cowley"

class _BostonViaCowleyViaMNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg(_UpgradeRollup):
    INITIAL_VERSION = "Rio"
    UPGRADE_VERSIONS = ["Miami","Orlando", "George", "MNR", "Cowley","Boston"]
    UPGRADE_HOTFIXES = [[], [], [], [], [], []]
    
class _BostonViaCowleyViaMNRRTMViaGeorgeAndOrlandoAndMiami(_UpgradeRollup):
    INITIAL_VERSION = "Miami"
    UPGRADE_VERSIONS = ["Orlando", "George", "MNR", "Cowley","Boston"]
    UPGRADE_HOTFIXES = [[], [], [], [], []]

class _BostonViaCowleyViaMNRRTMViaGeorgeAndOrlando(_UpgradeRollup):
    INITIAL_VERSION = "Orlando"
    UPGRADE_VERSIONS = ["George", "MNR", "Cowley","Boston"]
    UPGRADE_HOTFIXES = [[], [], [], []]

class _BostonViaCowleyViaMNRRTMViaGeorge(_UpgradeRollup):
    INITIAL_VERSION = "George"
    UPGRADE_VERSIONS = ["MNR", "Cowley","Boston"]
    UPGRADE_HOTFIXES = [[], [], []]

class _BostonViaCowleyViaMNRRTM(_UpgradeRollup):
    INITIAL_VERSION = "MNR"
    UPGRADE_VERSIONS = ["Cowley","Boston"]
    UPGRADE_HOTFIXES = [[], []]
    
class _BostonViaCowleyRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Cowley"
    UPGRADE_VERSIONS = ["Boston"]
    UPGRADE_HOTFIXES = [[]]

class _BostonRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Boston"

class _SanibelViaOxfordViaMNRRTMViaGeorgeAndOrlando(_UpgradeRollup):
    INITIAL_VERSION = "Orlando"
    UPGRADE_VERSIONS = ["George", "MNR", "Oxford","Sanibel"]
    UPGRADE_HOTFIXES = [[], [], [], []]

class _SanibelViaOxfordViaMNRRTMViaGeorge(_UpgradeRollup):
    INITIAL_VERSION = "George"
    UPGRADE_VERSIONS = ["MNR", "Oxford","Sanibel"]
    UPGRADE_HOTFIXES = [[], [], []]

class _SanibelViaOxfordViaMNRRTM(_UpgradeRollup):
    INITIAL_VERSION = "MNR"
    UPGRADE_VERSIONS = ["Oxford","Sanibel"]
    UPGRADE_HOTFIXES = [[], []]

class _SanibelViaOxfordRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Oxford"
    UPGRADE_VERSIONS = ["Sanibel"]
    UPGRADE_HOTFIXES = [[]]

class _SanibelRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Sanibel"

class _TampaViaSanibelViaOxfordViaMNRRTMViaGeorgeAndOrlando(_UpgradeRollup):
    INITIAL_VERSION = "Orlando"
    UPGRADE_VERSIONS = ["George", "MNR", "Oxford","Sanibel", "Tampa"]
    UPGRADE_HOTFIXES = [[], [], [], [], []]

class _TampaViaSanibelViaOxfordViaMNRRTMViaGeorge(_UpgradeRollup):
    INITIAL_VERSION = "George"
    UPGRADE_VERSIONS = ["MNR", "Oxford","Sanibel", "Tampa"]
    UPGRADE_HOTFIXES = [[], [], [], []]

class _TampaViaSanibelViaOxfordViaMNRRTM(_UpgradeRollup):
    INITIAL_VERSION = "MNR"
    UPGRADE_VERSIONS = ["Oxford","Sanibel", "Tampa"]
    UPGRADE_HOTFIXES = [[], [], []]

class _TampaViaSanibelViaOxfordRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Oxford"
    UPGRADE_VERSIONS = ["Sanibel", "Tampa"]
    UPGRADE_HOTFIXES = [[], []]

class _TampaViaSanibelRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Sanibel"
    UPGRADE_VERSIONS = ["Tampa"]
    UPGRADE_HOTFIXES = [[]]
    
class _TampaRTMUpg(_UpgradeRollup):
    INITIAL_VERSION = "Tampa"

class _FloodgateRollupUpg(_UpgradeRollup):
    INITIAL_VERSION = "Orlando HF3"

class _GeorgeUpdate1Upg(_UpgradeRollup):
    INITIAL_VERSION = "George Update 1"

class _BostonBeta1(_UpgradeRollup):
    INITIAL_VERSION = "Boston Beta1"

class _BostonBeta3(_UpgradeRollup):
    INITIAL_VERSION = "Boston Beta3"

class _BostonMNRAllHF(_UpgradeRollup):
    INITIAL_VERSION = "MNR"
    INITIAL_HOTFIXES = ["XS56E001","XS56E002","XS56E003","XS56E004","XS56E005","XS56E006","XS56E007","XS56E009","XS56E010", "XS56E011", "XS56E012", "XS56E013"]

class _BostonOxfAllHF(_UpgradeRollup):
    INITIAL_VERSION = "OXFORD"
    INITIAL_HOTFIXES = ["XS56ESP2001","XS56ESP2002","XS56ESP2003","XS56ESP2004","XS56ESP2005","XS56ESP2006","XS56ESP2007","XS56ESP2008","XS56ESP2009","XS56ESP2010","XS56ESP2011","XS56ESP2012","XS56ESP2014","XS56ESP2015","XS56ESP2016"]

class _BostonCowAllHF(_UpgradeRollup):
    INITIAL_VERSION = "Cowley"
    INITIAL_HOTFIXES = ["XS56EFP1001","XS56EFP1002","XS56EFP1004","XS56EFP1005","XS56EFP1006","XS56EFP1007","XS56EFP1008","XS56EFP1009","XS56EFP1010","XS56EFP1011","OXFHF"]  

class _BostonCowAllHFBobHF(_UpgradeRollup):
    INITIAL_VERSION = "Cowley"
    INITIAL_HOTFIXES = ["XS56EFP1001","XS56EFP1002","XS56EFP1004","XS56EFP1005","XS56EFP1006","XS56EFP1007","XS56EFP1008","XS56EFP1009","XS56EFP1010","XS56EFP1011","OXFHF","XS56ESP2001"]

class _SanibelBosAllHF(_UpgradeRollup):
    INITIAL_VERSION = "Boston"
    INITIAL_HOTFIXES = ["XS60E001","XS60E002","XS60E003","XS60E004","XS60E005","XS60E006","XS60E007","XS60E008","XS60E009","XS60E010","XS60E013","XS60E014","XS60E015","XS60E016"]

class _TampaSanibelAllHF(_UpgradeRollup):
    INITIAL_VERSION = "Boston"
    INITIAL_HOTFIXES = ["XS602E003","XS602E004","XS602E005"]

class _TampaOriginalSanibelAllHF(_UpgradeRollup):
    INITIAL_VERSION = "Boston"
    INITIAL_HOTFIXES = ["XS602E001", "XS602E002", "XS602E003","XS602E004","XS602E005"]

# Single host testcases

class TC8827(_MiamiRTMUpg):
    """Single host upgrade from Miami RTM"""
    pass

class TC8828(_MiamiHF1Upg):
    """Single host upgrade from Miami hotfix 1"""
    pass

class TC8829(_MiamiHF2Upg):
    """Single host upgrade from Miami hotfix 2"""
    pass

class TC8830(_MiamiHF3Upg):
    """Single host upgrade from Miami hotfix 3"""
    pass

class TC8847(_MiamiRTMViaRioUpg):
    """Single host upgrade from Miami RTM previously upgraded from Rio RTM"""
    pass

class TC8831(_OrlandoRTMUpg):
    """Single host upgrade from Orlando RTM"""
    pass

class TC8832(_OrlandoHF1Upg):
    """Single host upgrade from Orlando update 1"""
    pass

class TC8833(_OrlandoHF2Upg):
    """Single host upgrade from Orlando update 2"""
    pass

class TC8834(_OrlandoHF3Upg):
    """Single host upgrade from Orlando update 3"""
    pass

class TC9124(_OrlandoRTMViaMiamiUpg):
    """Single host upgrade from Orlando RTM previously upgraded from Miami RTM"""
    pass

class TC9125(_OrlandoRTMViaRioAndMiamiUpg):
    """Single host upgrade from Orlando RTM previously upgraded from Miami RTM and Rio RTM"""
    pass

class TC9139(_GeorgeBetaUpg):
    """Single host upgrade from George Beta"""
    pass

class TC11085(_GeorgeRTMUpg):
    """Single host upgrade from George RTM"""
    pass

class TC11086(_GeorgeHF1Upg):
    """Single host upgrade from George update 1"""
    pass

class TC11087(_GeorgeHF2Upg):
    """Single host upgrade from George update 2"""
    pass

class TC11088(_GeorgeRTMViaOrlandoUpg):
    """Single host upgrade from George RTM previously upgraded from Orlando RTM"""
    pass

class TC11089(_GeorgeRTMViaOrlandoAndMiamiUpg):
    """Single host upgrade from George RTM previously upgraded from Orlando RTM and Miami RTM"""
    pass

class TC11090(_GeorgeRTMViaOrlandoAndMiamiAndRioUpg):
    """Single host upgrade from George RTM previously upgraded from Orlando RTM, Miami RTM and Rio RTM"""
    pass

class TC11338(_MidnightRideBetaUpg):
    """Single host upgrade from Midnight Ride Beta"""
    pass

class TC12070(_MNRRTMUpg):
    """Single host upgrade from Midnight Ride RTM"""
    pass

class TC12072(_MNRRTMViaGeorgeUpg):
    """Single host upgrade from Midnight Ride RTM previously upgraded from George RTM"""
    pass

class TC12074(_MNRRTMViaGeorgeAndOrlandoUpg):
    """Single host upgrade from Midnight Ride RTM previously upgraded from George RTM and Orlando RTM"""
    pass

class TC12076(_MNRRTMViaGeorgeAndOrlandoAndMiamiUpg):
    """Single host upgrade from Midnight Ride RTM previously upgraded from George RTM, Orlando RTM and Miami RTM"""
    pass

class TC12078(_MNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg):
    """Single host upgrade from Midnight Ride RTM previously upgraded from George RTM, Orlando RTM, Miami RTM and Rio RTM"""
    pass

class TC14885(_CowleyViaMNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg):
    """Single host upgrade from Cowley RTM previously upgraded from MNR RTM,George RTM, Orlando RTM, Miami RTM and Rio RTM"""
    pass

class TC14886(_CowleyViaMNRRTMViaGeorgeAndOrlandoAndMiami):
    """Single host upgrade from Cowley RTM previously upgraded from MNR RTM, George RTM, Orlando RTM and Miami RTM"""
    pass

class TC14887(_CowleyViaMNRRTMViaGeorgeAndOrlando):
    """Single host upgrade from Cowley RTM previously upgraded from MNR RTM,George RTM and Orlando RTM"""
    pass

class TC14888(_CowleyViaMNRRTMViaGeorge):
    """Single host upgrade from Cowley RTM previously upgraded from MNR RTM previously upgraded from George RTM"""
    pass

class TC14889(_CowleyViaMNRRTM):
    """Single host upgrade from Cowley RTM previously upgraded from MNR RTM"""
    pass

class TC14890(_CowleyRTMUpg):
    """Single host upgrade from Cowley RTM"""
    pass

class TC17662(_BostonViaCowleyViaMNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg):
    """Single host upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM,George RTM, Orlando RTM, Miami RTM and Rio RTM"""
    pass

class TC17663(_BostonViaCowleyViaMNRRTMViaGeorgeAndOrlandoAndMiami):
    """Single host upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM, George RTM, Orlando RTM and Miami RTM"""
    pass
    
class TC17664(_BostonViaCowleyViaMNRRTMViaGeorgeAndOrlando):
    """Single host upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM,George RTM and Orlando RTM"""
    pass
    
class TC17665(_BostonViaCowleyViaMNRRTMViaGeorge):
    """Single host upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM previously upgraded from George RTM"""
    pass
    
class TC17666(_BostonViaCowleyViaMNRRTM):
    """Single host upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM"""
    pass

class TC17667(_BostonViaCowleyRTMUpg):
    """Single host upgrade from Boston RTM previously upgraded from Cowley RTM"""
    pass

class TC17668(_BostonRTMUpg):
    """Single host upgrade from Boston RTM"""
    pass

class TC19837(_TampaViaSanibelViaOxfordViaMNRRTMViaGeorgeAndOrlando):
    """Single Host Upgrade From Tampa, Sanibel, Oxford, MNR, George, Orlando"""
    pass

class TC19838(_TampaViaSanibelViaOxfordViaMNRRTMViaGeorge):
    """Single Host Upgrade From Tampa, Sanibel, Oxford, MNR, George"""
    pass

class TC19839(_TampaViaSanibelViaOxfordViaMNRRTM):
    """Single Host Upgrade From Tampa, Sanibel, Oxford, MNR"""
    pass

class TC19840(_TampaViaSanibelViaOxfordRTMUpg):
    """Single Host Upgrade From Tampa, Sanibel, Oxford"""
    pass

class TC19841(_TampaViaSanibelRTMUpg):
    """Single Host Upgrade From Tampa, Sanibel"""
    pass

class TC19842(_TampaRTMUpg):
    """Single Host Upgrade From Tampa"""
    pass

class TC19843(_SanibelViaOxfordViaMNRRTMViaGeorgeAndOrlando):
    """Single Host Upgrade From Sanibel, Oxford, MNR, George, Orlando"""
    pass

class TC19844(_SanibelViaOxfordViaMNRRTMViaGeorge):
    """Single Host Upgrade From Sanibel, Oxford, MNR, George"""
    pass

class TC19845(_SanibelViaOxfordViaMNRRTM):
    """Single Host Upgrade From Sanibel, Oxford, MNR"""
    pass

class TC19846(_SanibelViaOxfordRTMUpg):
    """Single Host Upgrade From Sanibel, Oxford"""
    pass

class TC19847(_SanibelRTMUpg):
    """Single Host Upgrade From Sanibel"""
    pass


class TC14963(_RioRTMFailUpg):
    """Single host upgrade check from Rio RTM"""
    pass

class TC14964(_MiamiRTMFailUpg):
    """Single host upgrade check from Miami RTM"""
    pass

class TC14965(_OrlandoRTMFailUpg):
    """Single host upgrade check from Orlando RTM"""
    pass

class TC14966(_GeorgeRTMFailUpg):
    """Single host upgrade check from George RTM"""
    pass

class TC14973(_BostonBeta1):
    """Single host upgrade from Boston Beta1"""
    pass

class TC14974(_BostonBeta3):
    """Single host upgrade from Boston Beta3"""
    pass

class TC14997(_BostonMNRAllHF):
    """Single host upgrade from MNR RTM plus all the hotfixes of MNR"""
    pass

class TC15000(_BostonOxfAllHF):
    """Single host upgrade from Oxford RTM plus all the hotfixes of Oxford"""
    pass

class TC15022(_BostonCowAllHF):
    """Single host upgrade from Cowley RTM plus all the hotfixes upto Oxford"""
    pass

class TC15023(_BostonCowAllHFBobHF):
    """Single host upgrade from Cowley RTM plus all the hotfixes upto Oxford plus Bob hotfix"""
    pass

class TC15629(_SanibelBosAllHF):
    """Single host upgrade from Boston RTM plus all the hotfixes of Boston"""
    pass

class TC17657(_TampaSanibelAllHF):
    """Single host upgrade from Sanibel RTM plus all the hotfixes of Sanibel"""
    pass

class TC17658(_TampaOriginalSanibelAllHF):
    """Single host upgrade from Sanibel RTM (original) plus all the hotfixes of Sanibel"""
    pass

class TC19859(_UpgradeRollup):
    """Single Host Upgrade From Tampa with All Hotfixes"""
    INITIAL_VERSION = "Tampa"

class TC19860(_UpgradeRollup):
    """Single Host Upgrade From Sanibel with All Hotfixes"""
    INITIAL_VERSION = "Sanibel"

class TC19861(_UpgradeRollup):
    """Single Host Upgrade From Boston with All Hotfixes"""
    INITIAL_VERSION = "Boston"

class TC19862(_UpgradeRollup):
    """Single Host Upgrade From Oxford with All Hotfixes"""
    INITIAL_VERSION = "Oxford"

class TC19863(_UpgradeRollup):
    """Single Host Upgrade From Cowley with All Hotfixes"""
    INITIAL_VERSION = "Cowley"

class TC19864(_UpgradeRollup):
    """Single Host Upgrade From MNR with All Hotfixes"""
    INITIAL_VERSION = "MNR"

class TC19865(_UpgradeRollup):
    """Rolling Pool Upgrade From Tampa with All Hotfixes"""
    INITIAL_VERSION = "Tampa"
    POOLED = True

class TC19866(_UpgradeRollup):
    """Rolling Pool Upgrade From Sanibel with All Hotfixes"""
    INITIAL_VERSION = "Sanibel"
    POOLED = True

class TC19867(_UpgradeRollup):
    """Rolling Pool Upgrade From Boston with All Hotfixes"""
    INITIAL_VERSION = "Boston"
    POOLED = True

class TC19868(_UpgradeRollup):
    """Rolling Pool Upgrade From Oxford with All Hotfixes"""
    INITIAL_VERSION = "Oxford"
    POOLED = True

class TC19869(_UpgradeRollup):
    """Rolling Pool Upgrade From Cowley with All Hotfixes"""
    INITIAL_VERSION = "Cowley"
    POOLED = True

class TC19870(_UpgradeRollup):
    """Rolling Pool Upgrade From MNR with All Hotfixes"""
    INITIAL_VERSION = "MNR"
    POOLED = True

# Pool testcases

class TC14967(_RioRTMFailUpg):
    """Rolling pool upgrade check from Rio RTM"""
    POOLED = True

class TC14968(_MiamiRTMFailUpg):
    """Rolling pool upgrade check from Miami RTM"""
    POOLED = True

class TC14970(_OrlandoRTMFailUpg):
    """Rolling pool upgrade check from Orlando RTM"""
    POOLED = True

class TC14969(_GeorgeRTMFailUpg):
    """Rolling pool upgrade check from George RTM"""
    POOLED = True

class TC8853(_MiamiRTMUpg):
    """Rolling pool upgrade from Miami RTM"""
    POOLED = True

class TC8855(_MiamiHF1Upg):
    """Rolling pool upgrade from Miami hotfix 1"""
    POOLED = True

class TC8854(_MiamiHF2Upg):
    """Rolling pool upgrade from Miami hotfix 2"""
    POOLED = True

class TC8859(_MiamiHF3Upg):
    """Rolling pool upgrade from Miami hotfix 3"""
    POOLED = True

class TC8861(_MiamiRTMViaRioUpg):
    """Rolling pool upgrade from Miami RTM previously upgraded from Rio RTM"""
    POOLED = True

class TC8860(_OrlandoRTMUpg):
    """Rolling pool upgrade from Orlando RTM"""
    POOLED = True

class TC8857(_OrlandoHF1Upg):
    """Rolling pool upgrade from Orlando update 1"""
    POOLED = True

class TC8858(_OrlandoHF2Upg):
    """Rolling pool upgrade from Orlando update 2"""
    POOLED = True

class TC8856(_OrlandoHF3Upg):
    """Rolling pool upgrade from Orlando update 3"""
    POOLED = True

class TC8856Quick(_OrlandoHF3onlyUpg):
    """Rolling pool upgrade from Orlando update 3 (skipping HF1, HF2)"""
    POOLED = True

class TC9126(_OrlandoRTMViaMiamiUpg):
    """Rolling pool upgrade from Orlando RTM previously upgraded from Miami RTM"""
    POOLED = True

class TC9127(_OrlandoRTMViaRioAndMiamiUpg):
    """Rolling pool upgrade from Orlando RTM previously upgraded from Miami RTM and Rio RTM"""
    POOLED = True

class TC9140(_GeorgeBetaUpg):
    """Rolling pool upgrade from George Beta"""
    POOLED = True

class TC11091(_GeorgeRTMUpg):
    """Rolling pool upgrade from George RTM"""
    POOLED = True

class TC11092(_GeorgeHF1Upg):
    """Rolling pool upgrade from George update 1"""
    POOLED = True

class TC11093(_GeorgeHF2Upg):
    """Rolling pool upgrade from George update 2"""
    POOLED = True

class TC11094(_GeorgeRTMViaOrlandoUpg):
    """Rolling pool upgrade from George RTM previously upgraded from Orlando RTM"""
    POOLED = True

class TC11095(_GeorgeRTMViaOrlandoAndMiamiUpg):
    """Rolling pool upgrade from George RTM previously upgraded from Orlando RTM and Miami RTM"""
    POOLED = True

class TC11096(_GeorgeRTMViaOrlandoAndMiamiAndRioUpg):
    """Rolling pool upgrade from George RTM previously upgraded from Orlando RTM, Miami RTM and Rio RTM"""
    POOLED = True

class TC11339(_MidnightRideBetaUpg):
    """Rolling pool upgrade from Midnight Ride Beta"""
    POOLED = True

class TC12071(_MNRRTMUpg):
    """Rolling pool upgrade from Midnight Ride RTM"""
    POOLED = True

class TC12073(_MNRRTMViaGeorgeUpg):
    """Rolling pool upgrade from Midnight Ride RTM previously upgraded from George RTM"""
    POOLED = True

class TC12075(_MNRRTMViaGeorgeAndOrlandoUpg):
    """Rolling pool upgrade from Midnight Ride RTM previously upgraded from George RTM and Orlando RTM"""
    POOLED = True

class TC12077(_MNRRTMViaGeorgeAndOrlandoAndMiamiUpg):
    """Rolling pool upgrade from Midnight Ride RTM previously upgraded from George RTM, Orlando RTM and Miami RTM"""
    POOLED = True

class TC12079(_MNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg):
    """Rolling pool upgrade from Midnight Ride RTM previously upgraded from George RTM, Orlando RTM, Miami RTM and Rio RTM"""
    POOLED = True

class TC14891(_CowleyViaMNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg):
    """Rolling pool upgrade from Cowley RTM previously upgraded from MNR RTM,George RTM, Orlando RTM, Miami RTM and Rio RTM"""
    POOLED = True

class TC14892(_CowleyViaMNRRTMViaGeorgeAndOrlandoAndMiami):
    """Rolling pool upgrade from Cowley RTM previously upgraded from MNR RTM, George RTM, Orlando RTM and Miami RTM"""
    POOLED = True

class TC14893(_CowleyViaMNRRTMViaGeorgeAndOrlando):
    """Rolling pool upgrade from Cowley RTM previously upgraded from MNR RTM,George RTM and Orlando RTM"""
    POOLED = True

class TC14894(_CowleyViaMNRRTMViaGeorge):
    """Rolling pool upgrade from Cowley RTM previously upgraded from MNR RTM previously upgraded from George RTM"""
    POOLED = True

class TC14895(_CowleyViaMNRRTM):
    """Rolling pool upgrade from Cowley RTM previously upgraded from MNR RTM"""
    POOLED = True

class TC14896(_CowleyRTMUpg):
    """Rolling pool upgrade from Cowley RTM"""
    POOLED = True

class TC17669(_BostonViaCowleyViaMNRRTMViaGeorgeAndOrlandoAndMiamiAndRioUpg):
    """Rolling pool upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM,George RTM, Orlando RTM, Miami RTM and Rio RTM"""
    POOLED = True
    
class TC17670(_BostonViaCowleyViaMNRRTMViaGeorgeAndOrlandoAndMiami):
    """Rolling pool upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM, George RTM, Orlando RTM and Miami RTM"""
    POOLED = True
    
class TC17671(_BostonViaCowleyViaMNRRTMViaGeorgeAndOrlando):
    """Rolling pool upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM,George RTM and Orlando RTM"""
    POOLED = True
    
class TC17672(_BostonViaCowleyViaMNRRTMViaGeorge):
    """Rolling pool upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM previously upgraded from George RTM"""
    POOLED = True
    
class TC17673(_BostonViaCowleyViaMNRRTM):
    """Rolling pool upgrade from Boston RTM previously upgraded from Cowley RTM, MNR RTM"""
    POOLED = True
    
class TC17674(_BostonViaCowleyRTMUpg):
    """Rolling pool upgrade from Cowley RTM"""
    POOLED = True

class TC17675(_BostonRTMUpg):
    """Rolling pool upgrade from Cowley RTM"""
    POOLED = True

class TC19848(_TampaViaSanibelViaOxfordViaMNRRTMViaGeorgeAndOrlando):
    """Rolling Pool Upgrade From Tampa, Sanibel, Oxford, MNR, George, Orlando"""
    POOLED = True
    
class TC19849(_TampaViaSanibelViaOxfordViaMNRRTMViaGeorge):
    """Rolling Pool Upgrade From Tampa, Sanibel, Oxford, MNR, George"""
    POOLED = True
    
class TC19850(_TampaViaSanibelViaOxfordViaMNRRTM):
    """Rolling Pool Upgrade From Tampa, Sanibel, Oxford, MNR"""
    POOLED = True

class TC19851(_TampaViaSanibelViaOxfordRTMUpg):
    """Rolling Pool Upgrade From Tampa, Sanibel, Oxford"""
    POOLED = True

class TC19852(_TampaViaSanibelRTMUpg):
    """Rolling Pool Upgrade From Tampa, Sanibel"""
    POOLED = True

class TC19853(_TampaRTMUpg):
    """Rolling Pool Upgrade From Tampa"""
    POOLED = True

class TC19854(_SanibelViaOxfordViaMNRRTMViaGeorgeAndOrlando):
    """Rolling Pool Upgrade From Sanibel, Oxford, MNR, George, Orlando"""
    POOLED = True

class TC19855(_SanibelViaOxfordViaMNRRTMViaGeorge):
    """Rolling Pool Upgrade From Sanibel, Oxford, MNR, George"""
    POOLED = True

class TC19856(_SanibelViaOxfordViaMNRRTM):
    """Rolling Pool Upgrade From Sanibel, Oxford, MNR"""
    POOLED = True

class TC19857(_SanibelViaOxfordRTMUpg):
    """Rolling Pool Upgrade From Sanibel, Oxford"""
    POOLED = True

class TC19858(_SanibelRTMUpg):
    """Rolling Pool Upgrade From Sanibel"""
    POOLED = True

class TC14975(_BostonBeta1):
    """Rolling pool upgrade from Boston Beta1"""
    POOLED = True

class TC14976(_BostonBeta3):
    """Rolling pool upgrade from Boston Beta3"""
    POOLED = True

class TC14998(_BostonMNRAllHF):
    """Rolling pool upgrade from MNR RTM plus all the hotfixes of MNR"""
    POOLED = True

class TC15001(_BostonOxfAllHF):
    """Rolling pool upgrade from Oxford RTM plus all the hotfixes of Oxford"""
    POOLED = True

class TC15024(_BostonCowAllHF):
    """Rolling pool upgrade from Cowley RTM plus all the hotfixes upto Oxford"""
    POOLED = True

class TC15025(_BostonCowAllHFBobHF):
    """Rolling pool upgrade from Cowley RTM plus all the hotfixes upto Oxford plus Bob hotfix"""
    POOLED = True

class TC15630(_SanibelBosAllHF):
    """Rolling pool upgrade from Boston RTM plus all the hotfixes of Boston"""
    POOLED = True

class TC17659(_TampaSanibelAllHF):
    """Rolling pool upgrade from Sanibel RTM plus all the hotfixes of Sanibel"""
    POOLED = True

class TC17660(_TampaOriginalSanibelAllHF):
    """Rolling pool upgrade from Sanibel RTM (original) plus all the hotfixes of Sanibel"""
    POOLED = True

class TCUnsignedHotfixChecks(xenrt.TestCase):
    """Unsigned hotfix contents and metadata checks"""
    def run(self, arglist):
    
        tempDir = xenrt.resources.TempDirectory()
        
        hotfixFiles = filter(self.__includeHotfixPredicate, self._getHotfixFiles(tempDir))
        xenrt.TEC().logverbose("Extracted %d hotfixes" % len(hotfixFiles))       
          
        for h in hotfixFiles:
            hotfixName = h.split('/')[-1]
            
            xenrt.TEC().logverbose("Hotfix = " + hotfixName)
            unpackLoc = xenrt.command("bash %s unpack" % h).strip()
           
            if not "/tmp/tmp" in unpackLoc:
                raise xenrt.XRTFailure("Didn't get hotfix tmp path for %s" % h)
            
            tmpUnpackDir = xenrt.resources.TempDirectory()
            xenrt.command("mv %s %s" % (unpackLoc, tmpUnpackDir.dir))
            tmp = os.path.join(tmpUnpackDir.dir, unpackLoc.rstrip('/').split('/')[-1])
            xenrt.TEC().logverbose("Unpacked hotfix located %s" % tmp)
            
            # view hotfix contents
            contents = xenrt.command("cat %s/CONTENTS | sort" % tmp).strip()
            xenrt.TEC().logverbose("SORTED CONTENTS: %s" % contents) 
            hotfixHead = xenrt.command("head -n100 %s" % h)
            
            #Run sub-tests
            self.runSubcase("_checkDuplicateLines", (h, tmp, contents, hotfixHead), hotfixName, "Duplicate lines in CONTENTS")
            self.runSubcase("_checkVersionRegex", (hotfixHead), hotfixName, "Version regex formatting")
            self.runSubcase("_checkSanibelBuildRegex", (hotfixHead), hotfixName, "Sanibel build regex value")
            self.runSubcase("_checkSweeneyBuildRegex", (hotfixHead), hotfixName, "Sweeney build regex value") 
            
            
    def __includeHotfixPredicate(self, name):
        if "test-hotfix" in name:
            xenrt.TEC().logverbose("Test hotfix %s found, skipping..." % name)
            return False
        
        if re.search("hotfix.*test.*[.]unsigned", name) != None:
            xenrt.TEC().logverbose("Test hotfix %s found, skipping..." % name)
            return False
        
        return True
                       
                
    """Sub-tests"""
    def _checkDuplicateLines(self, h, tmp, contents, metadata):
        """Check the contents file of the hotfix package does not have duplicate lines of of text in it"""

        if "XS62ESP1" in metadata or "XS60" in metadata or "XS5" in metadata:
            # There are duplicated lines and there's nothing we can do about it.
            return

        contentsUniq = xenrt.command("cat %s/CONTENTS | sort | uniq" % tmp).strip()
        if contents != contentsUniq:
            xenrt.TEC().logverbose("Contents are: %s" % contents) 
            xenrt.TEC().logverbose("Unique contents are: %s" % contentsUniq) 
            raise xenrt.XRTFailure("Duplicated lines in hotfix contents for %s" % h)

    def _checkVersionRegex(self, contents):
        """
        Check regex escaping:
        The unsigned hotfix contents must contain a line that looks like this:
        VERSION_REGEX="^6\.1\.0$"
        The regex must start with a caret and end with a dollar and have escaped dots.
        """
        xenrt.TEC().logverbose("Checking version regex....") 
        regexValue = self._extractField("VERSION_REGEX", contents)

        if regexValue == None:
            raise xenrt.XRTFailure("VERSION_REGEX field was not found in the hotfix") 
        
        if regexValue.count('^') != 1 or regexValue.count('\.') != 2 or regexValue.count('$') != 1:
            raise xenrt.XRTFailure("VERSION_REGEX value %s was misformed" % regexValue)

    def _checkSanibelBuildRegex(self, metadata):
        """
        If the unsigned hotfix url contains sanibel-lcm then the unsigned hotfix contents must contain:
        XS_BUILD_REGEX="^53456.$"
        """
        branchName = "sanibel-lcm"
        buildRegex = "^53456.$"
        self._checkBuildRegex(metadata, buildRegex, branchName)
        
    def _checkSweeneyBuildRegex(self, metadata):
        """
        If the unsigned hotfix url contains sweeney-lcm  the the unsigned hotfix contents must contain:
        XS_BUILD_REGEX="^58523.$"
        """
        branchName = "sweeney-lcm"
        buildRegex = "^58523.$"
        self._checkBuildRegex(metadata, buildRegex, branchName)
    
    """ Helper methods"""  
    def _checkBuildRegex(self, metadata, requiredRegex, branchName):
        xenrt.TEC().logverbose("Checking build regex....") 
        
        if not branchName in xenrt.TEC().lookup("INPUTDIR"):
            xenrt.TEC().logverbose("Not %s so skipping build regex test" % branchName) 
            return
        
        key = "XS_BUILD_REGEX"
        fieldValue = self._extractField(key, metadata)
        if fieldValue == None:
            raise xenrt.XRTFailure("Could not find a value for %s" % key) 
        
        if fieldValue !=  requiredRegex:
            raise xenrt.XRTFailure("Build regex was %s, but should have been %s" % (fieldValue, requiredRegex))
                
    def _checkPreCheckUuid(self, metadata, contents, uuid, expectedLabel, versionRegex, verifySubstring): 
        xenrt.TEC().logverbose("Checking pre-check uuid....") 
        if not self._versionRegexFound(versionRegex, metadata):
            xenrt.TEC().logverbose("Not %s so skipping pre-check uuid test" % versionRegex) 
            return
            
        labelValue = self._extractField("LABEL", metadata)
                
        if labelValue.startswith(expectedLabel):
            xenrt.TEC().logverbose("%s was in label - checking for uuid" % expectedLabel) 
            precheckLine = "precheck_script %s %s" %(verifySubstring, uuid)
            if not precheckLine in contents:
                raise xenrt.XRTFailure("Precheck script uuid not found in %s hotfix matching %s" % (versionRegex, precheckLine))
        else: 
            xenrt.TEC().logverbose("%s was not in label %s - skipping uuid check" % (labelValue, expectedLabel)) 
            
    def _checkPreCheckUuidNotMatchingLabel(self, metadata, contents, uuid, expectedLabel, versionRegex, verifySubstring): 
        xenrt.TEC().logverbose("Checking pre-check uuid....") 
        if not self._versionRegexFound(versionRegex, metadata):
            xenrt.TEC().logverbose("Not %s so skipping pre-check uuid test" % versionRegex) 
            return
            
        labelValue = self._extractField("LABEL", metadata)
                
        if not labelValue.startswith(expectedLabel):
            xenrt.TEC().logverbose("%s was not in label - checking for uuid" % expectedLabel) 
            precheckLine = "precheck_script %s %s" %(verifySubstring, uuid)
            if not precheckLine in contents:
                raise xenrt.XRTFailure("Precheck script uuid not found in %s hotfix matching %s" % (versionRegex, precheckLine))
        else: 
            xenrt.TEC().logverbose("%s was in label %s - skipping uuid check" % (labelValue, expectedLabel)) 
            
    def _versionRegexFound(self, versionRegex, metadata): 
        return versionRegex == self._extractField("VERSION_REGEX", metadata)
  
    def _getHotfixFiles(self, tempDir):
        wildcard = "*.unsigned"
        inputDir=xenrt.TEC().lookup("INPUTDIR").rstrip("/")
        unsignedHotfixesTarball = xenrt.TEC().getFiles( inputDir + "/" + wildcard)
        if unsignedHotfixesTarball == None:
            xenrt.TEC().logverbose("Could not find any files to tar up") 
            return []
        return xenrt.archive.TarGzArchiver().extractAndMatch(unsignedHotfixesTarball, tempDir.dir, "*")
        
    def _extractField(self, fieldName, contents):
        toMatch = fieldName + "="
        for line in contents.split("\n"):
            if toMatch in line:
                return line.split("=")[-1].strip('"')
        return None

class TCApplyHotfixes(xenrt.TestCase):
    """Apply a defined set of hotfixes to the host"""

    def run(self, arglist):
        self.host = self.getDefaultHost()
        patches = xenrt.TEC().lookup("BUNDLED_HOTFIX", {})
        patchIdents = patches.keys()
        patchIdents.sort()
        for p in patchIdents:
            self.host.applyPatch(xenrt.TEC().getFile(patches[p]), patchClean=True)
        self.host.reboot()

class TCRollingPoolHFX(TCRollingPoolUpdate):
    """
    Install Required HFX(s) for a current release on a pool 
    Install All Required Patches and THIS_HOTFIX and perform most significant apply action.
    """
    
    UPGRADE = False

class TC21007(TCRollingPoolUpdate):
    """
    Perform rolling pool update test with Xapi restart on hosts in intermediate states 
    during Rolling pool update. Regression test for HFX-1033, HFX-1034, HFX-1035.
    """

    def prepare(self, arglist):
        TCRollingPoolUpdate.prepare(self, arglist)
        self.preEvacuate = self.doRestartToolstack
        self.preReboot = self.doRestartToolstack

    def doRestartToolstack(self, host):
        host.restartToolstack()

class TCDecryptHotfix(xenrt.TestCase):
    """Test-case for CA-144941"""

    def run(self, arglist):
        workdir = xenrt.TEC().getWorkdir()
        if xenrt.command("test -e %s/patchapply" % workdir, retval="code") != 0:
            xenrt.getTestTarball("patchapply", extract=True, directory=workdir)

        try:
            self.getDefaultHost().applyPatch("%s/patchapply/hotfix-6.1.0-test1.xsupdate" % workdir)
        except Exception, ex:
            if not "incorrect version" in str(ex):
                raise xenrt.XRTFailure("Hotfix did not report 'incorrect version'")
        else:
            raise xenrt.XRTFailure("Hotfix should not have been applied as the version is wrong")

class TCDiscSpacePlugins(xenrt.TestCase):
    #TC-23995
    """Test case to verify plugins added for CAR-1711 are working properly"""
        
    def run(self, arglist=None):
        self.host = self.getDefaultHost()
        plugins = ["testAvailHostDiskSpacePlugin","testCheckPatchUploadPlugin", "testGetReclaimableSpacePlugin", "testCleanupDiskSpacePlugin"]
        #Create session on the host
        self.session = self.host.getAPISession(secure=False)
        self.sessionHost = self.session.xenapi.host.get_all()[0]
        for plugin in plugins:
            self.runSubcase(plugin, (),None , plugin)

    def testAvailHostDiskSpacePlugin(self):
        #Test functionality of 'get_avail_host_disk_space' plugin
        step("Call get_avail_host_disk_space plugin on host")
        actualAvailSpace = self.getAvailHostDiskSpace()/xenrt.MEGA
        xenrt.TEC().logverbose("Available disk space returned by plugin= %sMB" %(actualAvailSpace))
        
        step("Fetch available disk space from df")
        (totalSpace,usedSpace) =[int(i.strip()) for i in self.host.execdom0("df / -m | awk '{print$2,$3}' | sed 1d").split(" ")]
        expectedAvailSpace =  totalSpace-usedSpace
        xenrt.TEC().logverbose("Expected available disk space = %sMB" %(expectedAvailSpace))
        
        step("Verify space returned by the plugin is equal to the value given by df")
        if abs(actualAvailSpace-expectedAvailSpace) > 4:
            raise xenrt.XRTFailure("get_avail_host_disk_space plugin returned invalid data. Expected=%s. Actual=%s" % (expectedAvailSpace, actualAvailSpace))

    def testCheckPatchUploadPlugin(self):
        #Test functionality of 'check_patch_upload' plugin
        step("Call check_patch_upload plugin with size > dom0 available disk space: should returns false")
        if str(self.checkPatchUpload(self.getAvailHostDiskSpace()))=='True':
            raise xenrt.XRTFailure("check_patch_upload plugin returned True, Expected False")
        
        step("Call check_patch_upload plugin with size ~ dom0 available disk space: should returns true")
        if str(self.checkPatchUpload(self.getAvailHostDiskSpace()/3 - 2*xenrt.MEGA)) == 'False':
           raise xenrt.XRTFailure("check_patch_upload plugin returned False, Expected True")

        step("Call check_patch_upload plugin with size < dom0 available disk space: should returns true")
        if str(self.checkPatchUpload(self.getAvailHostDiskSpace()/3 - 20*xenrt.MEGA)) == 'False':
            raise xenrt.XRTFailure("check_patch_upload plugin returned False, Expected True")

    def testGetReclaimableSpacePlugin(self):
        #Test functionality of 'get_reclaimable_space' plugin        
        actualRecSpace = self.getReclaimableSpace()/xenrt.MEGA
        
        step("Call get_reclaimable_space plugin on host")
        xenrt.TEC().logverbose("get_reclaimable_disk_space returned %s" % (actualRecSpace))

        step("Verify value returned by the plugin is as expected")
        expectedRecSpace = 0
        res = self.host.execdom0("du -bs --separate-dirs /var/patch/ | awk '{print $1}'")
        if 'No such file or directory' not in res:
            expectedRecSpace += int(res)/xenrt.MEGA
        res = self.host.execdom0("du -bs /opt/xensource/patch-backup/ | awk '{print $1}'")
        if 'No such file or directory' not in res:
            expectedRecSpace += int(res)/xenrt.MEGA
        xenrt.TEC().logverbose("Expected reclaimable disk space is %s" % (expectedRecSpace))

        if abs(actualRecSpace-expectedRecSpace) > 4:
            raise xenrt.XRTFailure("get_reclaimable_disk_space plugin returned invalid data. Expected=%s. Actual=%s" % (actualRecSpace,expectedRecSpace))

    def testCleanupDiskSpacePlugin(self):
        #Test functionality of 'cleanup_disk_space' plugin
        availableSpace =  self.getAvailHostDiskSpace()/xenrt.MEGA
        reclaimableSpace = self.getReclaimableSpace()/xenrt.MEGA
        
        step("Call cleanup_disk_space plugin on host")
        self.session.xenapi.host.call_plugin(self.sessionHost,'disk-space','cleanup_disk_space',{})

        step("Verify available disk space is increased by value returned by getReclaimableSpace plugin")
        newAvailableSpace = self.getAvailHostDiskSpace()/xenrt.MEGA
        if abs(newAvailableSpace - (availableSpace + reclaimableSpace)) > 4:
            raise xenrt.XRTFailure("cleanup_disc_space plugin didn't free expected space. Expected=%s. Actual=%s" % (reclaimableSpace,newAvailableSpace-availableSpace))
        else:
            xenrt.TEC().logverbose("cleanup_disc_space freed expected amount of disk space: %s" % (newAvailableSpace-availableSpace))

    def getAvailHostDiskSpace(self):
        #Return available host disk space in Bytes
        return int(self.session.xenapi.host.call_plugin(self.sessionHost,'disk-space','get_avail_host_disk_space',{}))
            
    def getReclaimableSpace(self):
        #Return reclaimable disk space in Bytes
        return int(self.session.xenapi.host.call_plugin(self.sessionHost,'disk-space','get_reclaimable_disk_space',{}))

    def checkPatchUpload(self, size):
        #returns true if patch of given size can be uploaded, otherwise false
        return self.session.xenapi.host.call_plugin(self.sessionHost,'disk-space','check_patch_upload',{'size': '%s'%size})

    def postRun(self):
        #close the XenAPI session
        self.host.logoutAPISession(self.session)
