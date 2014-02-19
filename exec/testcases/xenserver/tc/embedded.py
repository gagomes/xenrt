#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for embedded edition specific features
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, os, os.path, copy, re, time
import xenrt

class TC6927(xenrt.TestCase):
    """Embedded edition host logging"""

    def __init__(self,tcid=None):
        # Logs that we make sure don't exist
        self.logsThatShouldntExist = ["/var/log/xensource.log","/var/log/SMlog",
                                      "/var/log/lastlog",
                                      "/var/log/xen/xenstored-access.log*"]

        xenrt.TestCase.__init__(self, tcid)

    def run(self,arglist):
        host = None

        # Get a host to use
        host = self.getDefaultHost()

        # Check this is an embedded host
        if not host.embedded:
            raise xenrt.XRTError("Asked to run on a non embedded host")

        for log in self.logsThatShouldntExist:
            if host.execdom0("ls %s" % (log),retval="code") == 0:
                raise xenrt.XRTFailure("Log %s exists" % (log))

        # Spam logs sufficiently to cause a syslog rotation and verify that the
        # rotated log has been compressed. Spam at least 1M to cause the rotate
        # Spams need to be unique or it just gets summarised with a last message
        # repeated x times...
        spamstring = ""
        for i in range(256):
            spamstring += "SPAM"

        host.execdom0("for ((i=0;i<1024;i+=1)); do logger -t xenrt %s-$i;"
                      " done" % (spamstring))

        # Check the text is there
        if host.execdom0("grep SPAM /var/log/messages > /dev/null",
                         retval="code") > 0:
            raise xenrt.XRTError("SPAM text not found in /var/log/messages "
                                 "before rotation")

        # Run logrotate (this may return an error if any log doesn't exist)
        host.execdom0("/usr/sbin/logrotate /etc/logrotate.conf || true")

        # Check the text isn't there any more
        if host.execdom0("grep SPAM /var/log/messages > /dev/null",
                         retval="code") == 0:
            raise xenrt.XRTError("SPAM text found in /var/log/messages after "
                                 "log rotation")

        # Check the rotated log has been compressed
        logs = ""
        try:
            logs = host.execdom0("ls /var/log/messages.*")
        except:
            raise xenrt.XRTFailure("Could not find rotated log")

        # Check the rotated log has been compressed
        if not "/var/log/messages.1.gz" in logs.split():
            raise xenrt.XRTFailure("Could not find /var/log/messages.1.gz")

        # Check this log contains our text
        host.execdom0("cp /var/log/messages.1.gz /tmp")
        host.execdom0("gunzip /tmp/messages.1.gz")
        if host.execdom0("grep SPAM /tmp/messages.1 > /dev/null",
                         retval="code") > 0:
            raise xenrt.XRTFailure("SPAM text not in first rotated log")                     

        for log in logs.split():
            # Check they all end in .gz (i.e. we haven't uncompressed)
            if not log.endswith(".gz"):
                raise xenrt.XRTFailure("Uncompressed rotated log %s found" % (log))

class TC6926(xenrt.TestCase):
    """OEM customisation using oem-rpm-install and the DDK"""

    def prepare(self, arglist):
        # Get a host
        self.host = self.getDefaultHost()

        # Check we can get the oem-rpm-install script
        oriscript = xenrt.TEC().getFile("oem-rpm-install",
                                        "oem-phase-1/oem-rpm-install")
        if not oriscript:
            raise xenrt.XRTError("Cannot find oem-rpm-install script in build "
                                 "output")

        # Import the DDK
        self.guest = self.host.importDDK()
        self.guest.createVIF(bridge=self.host.getPrimaryBridge())
        self.guest.createDisk(sizebytes=5368709120,userdevice="xvdc")
        self.guest.start()
        time.sleep(30) # Give it some time to start
        self.guest.existing(self.host)

        # Set up the storage space
        self.guest.execguest("mkfs.ext3 /dev/xvdc")
        self.guest.execguest("mkdir -p /mnt/ori && mount /dev/xvdc /mnt/ori")

        # Create a workdir, and copy the script and our bits to the DDK
        self.workdir = "/mnt/ori"
        self.guest.execguest("wget '%s/oem-rpm-install.tgz' -O - | "
                             "tar -zx -C %s" % 
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE"),
                              self.workdir))

        # Install squashfstools
        self.guest.execguest("rpm -ivh %s/oem-rpm-install/"
                             "squashfs-tools-3.0-4.i386.rpm" % (self.workdir)) 

        sftp = self.guest.sftpClient()
        sftp.copyTo(oriscript,"%s/oem-rpm-install.sh" % (self.workdir))

        # Copy the raw embedded image to the guest
        basename = xenrt.TEC().lookup("EMBEDDED_IMAGE", "embedded.img")
        self.imgname = basename
        imgfile = xenrt.TEC().getFile(basename)
        if not imgfile:
            imgfile = xenrt.TEC().getFile("oem-phase-1/%s" % (basename))
        if not imgfile:
            imgfile = xenrt.TEC().getFile("oem-phase-2/%s" % (basename))
        if not imgfile:
            raise xenrt.XRTError("No XE embedded image file (%s) found" %
                                 (basename))

        sftp.copyTo(imgfile,"%s/%s" % (self.workdir,basename))

        sftp.close()

        # Set up a controller workdir
        self.c_workdir = xenrt.TEC().getWorkdir()

    def run(self, arglist):
        # Use the oem-rpm-install script from the build outputs to merge one set
        # of customisations with the raw embedded edition
        # First set of customisations are rsync + lynx RPMs, and a FS overlay
        self.guest.execguest("%s/oem-rpm-install.sh -v "
                             "-i %s/oem-rpm-install/RPMs1 "
                             "-bo %s/oem-rpm-install/fs1 %s/%s" % (self.workdir,
                                                                self.workdir,
                                                                self.workdir,
                                                                self.workdir,
                                                                self.imgname),
                             timeout=3600)

        # Re-run oem-rpm-install to merge the second set of customisations into 
        # the image modified in the previous step
        # Second set of customisations are make + nmap RPMs, and an overlay
        self.guest.execguest("%s/oem-rpm-install.sh -v "
                             "-i %s/oem-rpm-install/RPMs2 "
                             "-ao %s/oem-rpm-install/fs2 %s/%s" % (self.workdir,
                                                                self.workdir,
                                                                self.workdir,
                                                                self.workdir,
                                                                self.imgname),
                             timeout=3600)

        # Copy the new image back to the XenRT controller
        sftp = self.guest.sftpClient()
        sftp.copyFrom("%s/%s" % (self.workdir,self.imgname),
                      "%s/%s" % (self.c_workdir,self.imgname))
        sftp.close()

        # Install the new image onto the same host we originally used
        self.host.installEmbedded(image="%s/%s" % (self.c_workdir,self.imgname))

        # Verify the installation and check both sets of customisations are in 
        # the installed image
        # TODO add self.host.check() once this has been modified to cope with embedded
        try:
            self.host.execdom0("which rsync")
            self.host.execdom0("which lynx")
        except:
            raise xenrt.XRTFailure("First set of RPM customisations not "
                                   "present in resulting image")
        try:
            data = self.host.execdom0("md5sum /usr/xenrt_custom_1",
                                      level=xenrt.RC_ERROR).strip()
            if not data.startswith("df96d0b00d0a0a3a94632986cd737718 "):
                raise xenrt.XRTFailure("/usr/xenrt_custom_1 from first set of "
                                       "customisations present but md5sum does "
                                       "not match!")
            data = self.host.execdom0("md5sum /usr/xenrt_custom_2",
                                      level=xenrt.RC_ERROR).strip()
            if not data.startswith("6564f765025b68822c4583f6f1bb5f03 "):
                raise xenrt.XRTFailure("/usr/xenrt_custom_2 from first set of "
                                       "customisations present but md5sum does "
                                       "not match!")
        except xenrt.XRTError, e:
            raise xenrt.XRTFailure("First set of filesystem customisations "
                                   "not present in resulting image")

        try:
            self.host.execdom0("which make")
            self.host.execdom0("which nmap")
        except:
            raise xenrt.XRTFailure("Second set of RPM customisations not "
                                   "present in resulting image")
        try:
            data = self.host.execdom0("md5sum /etc/xenrt_ecustom_1",
                                      level=xenrt.RC_ERROR).strip()
            if not data.startswith("ffe7737df5c4b23b4961ba88ef06565f "):
                raise xenrt.XRTFailure("/etc/xenrt_ecustom_1 from first set of "
                                       "customisations present but md5sum does "
                                       "not match!")
            data = self.host.execdom0("md5sum /etc/xenrt_ecustom_2",
                                      level=xenrt.RC_ERROR).strip()
            if not data.startswith("fe66818d36edee4b099ec23cb06b7f4c "):
                raise xenrt.XRTFailure("/etc/xenrt_ecustom_2 from first set of "
                                       "customisations present but md5sum does "
                                       "not match!")
        except xenrt.XRTError, e:
            raise xenrt.XRTFailure("Second set of filesystem customisations "
                                   "not present in resulting image")

class TC7348(xenrt.TestCase):
    """OEM vendor name should be shown in the HVM system-manufacturer"""

    def dmidecode(self, dmistring):
        d = string.strip(self.guest.execguest("dmidecode -s %s" % (dmistring)))
        i = self.host.getInventoryItem("OEM_MANUFACTURER")
        if i == "Citrix":
            i = "Xen"
        if d != i:
            raise xenrt.XRTFailure("HVM BIOS %s '%s' does not match "
                                   "OEM_MANUFACTURER '%s'" % (dmistring, d, i))
    
    def run(self, arglist):

        repository = string.split(xenrt.TEC().lookup(["RPM_SOURCE",
                                                      "rhel51",
                                                      "x86-32",
                                                      "HTTP"]))[0]
                    
        # Get a host to install on
        self.host = self.getDefaultHost()

        # Choose a template
        template = self.host.chooseTemplate("TEMPLATE_NAME_UNSUPPORTED_HVM")

        # Create an empty guest object
        self.guest = self.host.guestFactory()(xenrt.randomGuestName(),
                                              template)
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        self.guest.arch = "x86-32"
        self.guest.windows = False
        self.guest.setVCPUs(1)
        self.guest.setMemory(512)
        self.guest.install(self.host,
                           repository=repository,
                           distro="rhel51",
                           method="HTTP",
                           pxe=True,
                           notools=True)

        #self.runSubcase("dmidecode",
        #                ("bios-vendor"),
        #                "HVMBIOS",
        #                "bios-vendor")
        self.runSubcase("dmidecode",
                        ("system-manufacturer"),
                        "HVMBIOS",
                        "system-manufacturer")
        
        # Shutdown the VM
        self.guest.shutdown()

class _TC7327(xenrt.TestCase):

    host = None

    def setup(self):
        # Install a VM on one host to act as an iSCSI target
        peerhost = self.getHost("RESOURCE_HOST_1")
        self.iscsivm, self.iqn = self.makeTarget(peerhost)
        self.iscsivm.createISCSITargetLun(0, 128)
        self.lun = xenrt.ISCSIIndividualLun(None,
                                            0,
                                            server=self.iscsivm.getIP(),
                                            targetname=self.iqn)
        
    def makeTarget(self, host):
        guest = host.createGenericLinuxGuest()
        self.uninstallOnCleanup(guest)
        iqn = guest.installLinuxISCSITarget()
        return guest, iqn

    def createRemoteDB(self):
        self.host.setIQN("xenrt-test-iqn-TC7327")
        self.host.setupSharedDB(self.lun)
        self.host.execdom0("touch /var/xapi/shared_db/xenrtflag")

    def connectRemoteDB(self):
        self.host.setupSharedDB(self.lun, existing=True)
        if self.host.execdom0("test -e /var/xapi/shared_db/xenrtflag",
                              retval="code") != 0:
            raise xenrt.XRTFailure("Reconnected remote DB looks like it "
                                   "has been reformated")

    def databaseUpdating(self):
        # Perform an operation and verify the database is updated
        prevgen = int(self.host.execdom0(\
            "cat /var/xapi/shared_db%s/db/state.db.generation" % 
            (self.host.getDBCompatVersion())))
        self.host.setHostParam("other-config:TC7327", "%u" % (xenrt.timenow()))
        time.sleep(360)
        newgen = int(self.host.execdom0(\
            "cat /var/xapi/shared_db%s/db/state.db.generation" %
            (self.host.getDBCompatVersion())))
        if not newgen > prevgen:
            raise xenrt.XRTFailure("Remote database generation did not "
                                   "increase after an operation was performed")

    def rebootHost(self):
        # Reboot the host
        self.host.reboot()
        # Verify the database is mounted
        self.host.checkSharedDB()

    def removeDatabase(self):
        # Remove the remote database
        self.host.disableSharedDB()

    def postRun(self):
        try:
            self.host.disableSharedDB()
        except:
            pass
        try:
            self.host.execdom0("/etc/init.d/xapi start")
        except:
            pass

class TC7327(_TC7327):
    """Operation of agent database on shared iSCSI."""

    def run(self, arglist):

        self.host = self.getHost("RESOURCE_HOST_0")
        self.setup()

        if self.runSubcase("createRemoteDB", (), "RemoteDB", "Create") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("databaseUpdating", (), "RemoteDB", "Operating") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("rebootHost", (), "RemoteDB", "Reboot") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("removeDatabase", (), "RemoteDB", "Remove") != \
                xenrt.RESULT_PASS:
            return

class TC7362(_TC7327):
    """Set up remote agent database on iSCSI using a LUNid other than 0"""

    def createRemoteDB(self):
        self.host.setIQN("xenrt-test-iqn-TC7327")
        self.iscsivm.createISCSITargetLun(1, 256)
        self.lun1 = xenrt.ISCSIIndividualLun(None,
                                             1,
                                             server=self.iscsivm.getIP(),
                                             targetname=self.iqn)
        self.host.setupSharedDB(self.lun1)
        df = int(self.host.execdom0("df -P -m /var/xapi/shared_db | "
                                    "tail -n1 | awk '{print $2}'"))
        if df < 240 or df > 280:
            raise xenrt.XRTFailure("The size (%uMB) of the volume mounted on "
                                   "/var/xapi/shared_db is not the 256MB we "
                                   "were expecting" % (df))

    def run(self, arglist):

        self.host = self.getHost("RESOURCE_HOST_0")
        self.setup()

        if self.runSubcase("createRemoteDB", (), "RemoteDB", "CreateOnLUN1") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("databaseUpdating", (), "RemoteDB", "Operating") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("rebootHost", (), "RemoteDB", "Reboot") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("removeDatabase", (), "RemoteDB", "Remove") != \
                xenrt.RESULT_PASS:
            return

class TC7360(_TC7327):
    """Repeated create and remove of remote database on iSCSI"""

    ITERATIONS = 50

    def run(self, arglist):

        self.host = self.getHost("RESOURCE_HOST_0")
        self.setup()

        i = 0
        try:
            while i < self.ITERATIONS:
                i = i + 1
                igroup = "Iter%u" % (i)
                if self.runSubcase("createRemoteDB", (), igroup, "Create") != \
                       xenrt.RESULT_PASS:
                    return
                if self.runSubcase("databaseUpdating", (), igroup, "Operating") != \
                       xenrt.RESULT_PASS:
                    return
                if self.runSubcase("removeDatabase", (), igroup, "Remove") != \
                       xenrt.RESULT_PASS:
                    return
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (i, self.ITERATIONS))

class TC7361(_TC7327):
    """Repeated create and re-attach of remote database on iSCSI"""

    ITERATIONS = 50

    def run(self, arglist):

        self.host = self.getHost("RESOURCE_HOST_0")
        self.setup()

        if self.runSubcase("createRemoteDB", (), "Initial", "Create") != \
                xenrt.RESULT_PASS:
            return
        if self.runSubcase("removeDatabase", (), "Initial", "Remove") != \
               xenrt.RESULT_PASS:
            return

        i = 0
        try:
            while i < self.ITERATIONS:
                i = i + 1
                igroup = "Iter%u" % (i)
                if self.runSubcase("connectRemoteDB", (), igroup, "Create") != \
                       xenrt.RESULT_PASS:
                    return
                if self.runSubcase("databaseUpdating", (), igroup, "Operating") != \
                       xenrt.RESULT_PASS:
                    return
                if self.runSubcase("removeDatabase", (), igroup, "Remove") != \
                       xenrt.RESULT_PASS:
                    return
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (i, self.ITERATIONS))

class TC7374(xenrt.TestCase):
    """OEM embedded web page must refer to the correct OEM"""

    URLSTEM = "http://www.citrix.com/xenserver/"
    EXCLUDES = ["http://www.citrix.com/xenserver/try"]

    def run(self, arglist):

        host = self.getDefaultHost()
        ver = host.getInventoryItem("PRODUCT_VERSION")
        urlstem = string.replace(self.URLSTEM, "@PRODUCT_VERSION@", ver)
        oem = string.split(host.getOEMManufacturer())[0].lower()

        # Get the HTML
        data = host.execdom0("cat /opt/xensource/www/index.html")

        # Find all "http://www.citrix.com/xenserver"* URL
        xenrt.TEC().logverbose("Looking for URLs starting with %s" % (urlstem))
        urls = re.findall("(%s[^\"]+)" % (urlstem), data)
        for ex in self.EXCLUDES:
            exurl = string.replace(ex, "@PRODUCT_VERSION@", ver)
            if exurl in urls:
                urls.remove(exurl)
        if len(urls) == 0:
            return

        # Get the list of vendors
        vendors = {}
        for url in urls:
            v = string.replace(url, urlstem, "").split('/')[0].lower()
            if not v in vendors.keys():
                vendors[v] = []
            vendors[v].append(url)
        for v in vendors.keys():
            if v != oem:
                raise xenrt.XRTFailure("Found URL(s) %s in OEM %s image" %
                                       (string.join(vendors[v]), oem))

class TC8284(xenrt.TestCase):
    """Explicit claiming of a local disk with an active config volume"""

    ITERATIONS = 10
    
    def prepare(self, arglist):
        # Get a host
        self.host = self.getDefaultHost()

        # Reset to a fresh install and ensure we have a local disk
        # with a config volume
        self.host.resetToFreshInstall()
        self.host.reboot()

        self.disk = None
        confdisk = self.host.execdom0("/usr/sbin/pvs --noheadings "
                                      "--separator , | /bin/grep XenConfig | "
                                      "/bin/cut -f1 -d, | "
                                      "/bin/sed 's/p\?[0-9]*$//' | "
                                      "/bin/sed 's/\ *//'").strip()
        
        # If we don't have a disk claimed already claim one now
        if not confdisk:
            data = self.host.execdom0("/opt/xensource/libexec/list_local_disks")
            lines = data.splitlines()
            if len(lines) == 0:
                raise xenrt.XRTError("Cannot find a local disk to claim")
            disktoclaim = eval(lines[0])[0]
            self.host.execdom0("/opt/xensource/libexec/delete-partitions-and-claim-disk %s" % (disktoclaim))
            self.host.reboot()
            self.disk = disktoclaim
        else:
            # Find the by-id path for this disk
            byids = self.host.execdom0("ls /dev/disk/by-id/*").split()
            for byid in byids:
                disk = self.host.execdom0("readlink -f %s" % (byid)).strip()
                if disk == confdisk:
                    self.disk = byid
                    break

        if not self.disk:
            raise xenrt.XRTError("Could not determine disk to use for test")

    def findSR(self, disk, msg=""):
        srrawparts = self.host.execdom0("/usr/sbin/pvs --noheadings "
                                        "--separator , | "
                                        "/bin/grep XenStorage | "
                                        "/bin/cut -f1 -d, | "
                                        "/bin/sed 's/\ *//'").split()
        diskparts = self.host.execdom0("ls %s?*" % (disk)).split()
        srpart = None
        for d in diskparts:
            diskrawpart = self.host.execdom0("readlink -f %s" % (d)).strip()
            if diskrawpart in srrawparts:
                srpart = d
                break
        if not srpart:
            raise xenrt.XRTError("No SR volume on our test disk %s" % (msg),
                                 disk)
        srs = self.host.minimalList("pbd-list",
                                    "sr-uuid",
                                    "device-config:device=%s" %
                                    (srpart))
        if len(srs) == 0:
            raise xenrt.XRTError("SR not found in database %s" % (msg),
                                 "device %s" % (srpart))
        return srs[0]

    def run(self, arglist):

        rawnode = self.host.execdom0("readlink -f %s" % (self.disk)).strip()

        i = 0
        try:
            while i < self.ITERATIONS:
                xenrt.TEC().logdelimit("loop iteration %u" % (i))
                
                # Check the config volume on the disk is in use
                try:
                    self.host.execdom0("mount | grep xsconfig | grep XenConfig")
                except:
                    raise xenrt.XRTError("Config volume not mounted")
                confdisk = self.host.execdom0("/usr/sbin/pvs --noheadings "
                                              "--separator , | "
                                              "/bin/grep XenConfig | "
                                              "/bin/cut -f1 -d, | "
                                              "/bin/sed 's/p\?[0-9]*$//' | "
                                              "/bin/sed 's/\ *//'").strip()
                if rawnode != confdisk:
                    raise xenrt.XRTError("Config volume is not on our test disk",
                                         "Conf on %s, test disk %s (%s)" %
                                         (confdisk, rawnode, self.disk))

                # Find the SR on the disk
                sruuid = self.findSR(self.disk)

                # Claim the disk
                xenrt.TEC().progress("Claiming disk %s (iteration %u)" %
                                     (self.disk, i))
                self.host.execdom0("/opt/xensource/libexec/delete-partitions-and-claim-disk %s" % (self.disk))

                # Check the old SR has gone
                srs = self.host.minimalList("sr-list")
                if sruuid in srs:
                    raise xenrt.XRTFailure("SR still in database after "
                                           "reclaiming disk",
                                           sruuid)

                # Check we have a new SR on the disk
                sruuid = self.findSR(self.disk, "after claim")

                # Reboot
                self.host.reboot()

                i = i + 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (i, self.ITERATIONS))

class TC8356(xenrt.TestCase):
    """Verify frequently-written /etc files are not on Flash in OEM edition"""

    def run(self, arglist=None):
        host = self.getDefaultHost()

        # Get the list of files
        data = host.execdom0("cat /etc/freq-etc/LIST")
        files = [ file.strip() for file in data.splitlines() ]
        for file in files:
            if host.execdom0("ls %s" % (file), retval="code") == 0:
                # File exists, check if it's a symlink
                try:
                    sl = host.execdom0("readlink %s" % (file)).strip()
                    # Does destination exist?
                    if host.execdom0("ls %s" % (sl), retval="code") != 0:
                        # That's all we need to check
                        continue
                    # Check where it's pointing to is a tmpfs
                    if not "tmpfs" in host.execdom0("df -T %s" % (sl)):
                        raise xenrt.XRTFailure("File listed in "
                                               "/etc/freq-etc/LIST is symlinked"
                                               " to a non tmpfs", file)
                except:
                    # readlink returns an error if the file isn't a link
                    raise xenrt.XRTFailure("File listed in /etc/freq-etc/LIST "
                                           "is not a symlink", data=file)

        # Now check the functionality
        # Create a dummy file, and make it a frequently written one
        host.execdom0("echo abcd > /etc/xenrt_test")
        host.execdom0("echo /etc/xenrt_test >> /etc/freq-etc/LIST")
        host.cliReboot()

        # Check it is now a symlink, on tmpfs, with accurate data
        try:
            sl = host.execdom0("readlink /etc/xenrt_test").strip()
            # Check it's on tmpfs
            if not "tmpfs" in host.execdom0("df -T %s" % (sl)):
                raise xenrt.XRTFailure("Test file added to /etc/freq-etc/LIST "
                                       "was moved but not to a tmpfs")
            # Check the data
            data = host.execdom0("cat /etc/xenrt_test")
            if data.strip() != "abcd":
                raise xenrt.XRTFailure("Test file added to /etc/freq-etc/LIST "
                                       "was moved to tmpfs but data changed",
                                       data="Expecting abcd but found %s" % 
                                            (data.strip()))
        except:
            # Not a symlink!
            raise xenrt.XRTFailure("Test file added to /etc/freq-etc/LIST did "
                                   "not get moved from /etc")

        # Change the data and reboot
        host.execdom0("echo efgh > /etc/xenrt_test")
        host.cliReboot()

        # Check it is still a symlink, on tmpfs, with accurate data
        try:
            sl = host.execdom0("readlink /etc/xenrt_test").strip()
            # Check it's on tmpfs
            if not "tmpfs" in host.execdom0("df -T %s" % (sl)):
                raise xenrt.XRTFailure("Test file added to /etc/freq-etc/LIST "
                                       "was moved but not to a tmpfs after "
                                       "reboot")
            # Check the data
            data = host.execdom0("cat /etc/xenrt_test")
            if data.strip() != "efgh":
                raise xenrt.XRTFailure("Test file added to /etc/freq-etc/LIST "
                                       "lost data changed while on tmpfs",
                                       data="Expecting efgh but found %s" %
                                            (data.strip()))
        except:
            # Not a symlink!
            raise xenrt.XRTFailure("Test file added to /etc/freq-etc/LIST "
                                   "reappeared in /etc after reboot")

class TC1461(xenrt.TestCase):
    """OMSA Sanity Test"""

    def prepare(self, arglist=None):
        img = xenrt.TEC().lookup("EMBEDDED_IMAGE", None)
        if img and not "dell" in img.lower():
            xenrt.TEC().skip("Not running OMSA test on non-Dell OEM SKU")
            return
        self.host = self.getDefaultHost()
        manf = self.host.execdom0("dmidecode -s system-manufacturer")
        if not "Dell" in manf:
            raise xenrt.XRTError("Cannot run test on non-Dell hardware")

    def serviceStatus(self):
        data = self.host.execdom0("srvadmin-services.sh status")
        notrunning = []
        for line in data.splitlines():
            if not "is running" in line:
                notrunning.append(line.split()[0])
        if len(notrunning) > 0:
            raise xenrt.XRTFailure("One or more OMSA services not running: %s"
                                   % (string.join(notrunning)))

    def omreportSystemSummary(self):
        data = self.host.execdom0("omreport system summary")
        missing = []
        for keyword in ["XenServer",
                        self.host.productRevision,
                        "PowerEdge",
                        "Processor 1",
                        "Total Installed Capacity",
                        "Network Interface",
                        "Firmware Information"]:
            if not keyword in data:
                missing.append(keyword)
        if len(missing) > 0:
            raise xenrt.XRTFailure("One or more expected keyword not found in "
                                   "'omreport system summary': %s" %
                                   (string.join(missing, ", ")))
        serial = self.host.getInventoryItem("MACHINE_SERIAL_NUMBER")
        if serial:
            if not serial in data:
                raise xenrt.XRTFailure("Could not find machine serial number "
                                       "(Service Tag) in 'omreport system "
                                       "summary' output",
                                       serial)

    def checkSymlink(self, path, target):
        t = self.host.execdom0("readlink %s" % (path)).strip()
        if not t:
            raise xenrt.XRTFailure("%s is not a symlink" % (path))
        if t != target:
            raise xenrt.XRTFailure("%s does not link to %s (goes to %s)" %
                                   (path, target, t))

    def omReportError(self):
        data = self.host.execdom0("omreport -? | cat")
        if "error" in data.lower():
            raise xenrt.XRTFailure("Error in 'omreport -?' output")

    def omcli32ININoBlade(self):
        if self.host.execdom0("test -e /etc/dell/srvadmin/oma/ini/omcli32.ini",
                              retval="code") == 0:
            data = self.host.execdom0("cat /etc/dell/srvadmin/oma/ini/omcli32.ini")
        elif self.host.execdom0("test -e /etc/srvadmin/oma/ini/omcli32.ini",
                                retval="code") == 0:
            data = self.host.execdom0("cat /etc/srvadmin/oma/ini/omcli32.ini")
        else:
            raise xenrt.XRTFailure("Cannot find omcli32.ini")
        if "blade" in data.lower():
            raise xenrt.XRTFailure("'blade' found in omcli32.ini")

    def checkHTTPSOnline(self):
        f = xenrt.TEC().tempFile()
        xenrt.command("wget --no-check-certificate -O %s 'https://%s:1311/'" %
                      (f, self.host.getIP()))

    def checkracadm(self):
        data = self.host.execdom0("racadm getsysinfo | cat")
        if not "PowerEdge" in data:
            raise xenrt.XRTFailure("Could not find 'PowerEdge' in "
                                   "'racadm getsysinfo' output")
        serial = self.host.getInventoryItem("MACHINE_SERIAL_NUMBER")
        if serial:
            if not serial in data:
                raise xenrt.XRTFailure("Could not find machine serial number "
                                       "(Service Tag) in 'racadm getsysinfo' "
                                       "output",
                                       serial)

    def run(self, arglist=None):

        self.runSubcase("serviceStatus", (), "Service", "Status")
        self.runSubcase("omreportSystemSummary",
                        (),
                        "omreport",
                        "SystemSummary")
        #self.runSubcase("checkSymlink",
        #                ("/opt/dell/srvadmin/oma/ini",
        #                 "/etc/dell/srvadmin/oma/ini"),
        #                "OMASymlink",
        #                "ini")
        #self.runSubcase("checkSymlink",
        #                ("/opt/dell/srvadmin/oma/log",
        #                 "/var/log/dell/srvadmin/oma/log"),
        #                "OMASymlink",
        #                "log")
        #self.runSubcase("checkSymlink",
        #                ("/opt/dell/srvadmin/oma/run",
        #                 "/tmp/dell/srvadmin/oma/run"),
        #                "OMASymlink",
        #                "run")
        #self.runSubcase("checkSymlink",
        #                ("/opt/dell/srvadmin/shared/.ipc",
        #                 "/tmp/dell/srvadmin/shared/.ipc"),
        #                "OMASymlink",
        #                "ipc")
        self.runSubcase("omReportError", (), "omreport", "Error")
        self.runSubcase("omcli32ININoBlade", (), "omcli32", "Blade")
        self.runSubcase("checkHTTPSOnline", (), "HTTPS", "Online")
        self.runSubcase("checkracadm", (), "racadm", "getsysinfo")
        
