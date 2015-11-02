#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for storage features
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, os.path, json, random, xml.dom.minidom
import sys, traceback
import xenrt
from xenrt.lazylog import *


class _AbstractLinuxHostedNFSServer(object):
    def __init__(self, paths):
        self.paths = paths
        for path in self.paths:
            if not path.startswith('/'):
                raise ValueError('absolute path expected')

    def _getExportsLine(self):
        raise NotImplementedError('This is an abstract class')

    def _getCommandsToPrepareSharedDirectory(self):
        raise NotImplementedError('This is an abstract class')

    def getStorageRepositoryClass(self):
        raise NotImplementedError('This is an abstract class')

    def _prepareSharedDirectory(self, guest):
        for command in self._getCommandsToPrepareSharedDirectory():
            guest.execguest(command)

    def createNFSExportOnGuest(self, guest):
        guest.execguest(
            "apt-get install -y --force-yes nfs-kernel-server nfs-common "
            "portmap"
        )

        # Create a dir and export it
        self._prepareSharedDirectory(guest)
        guest.execguest("echo '%s' > /etc/exports" % self._getExportsLine())
        guest.execguest("/etc/init.d/portmap start || /etc/init.d/rpcbind start")
        guest.execguest("/etc/init.d/nfs-common start || true")
        guest.execguest("/etc/init.d/nfs-kernel-server start || true")


class _LinuxHostedNFSv3Server(_AbstractLinuxHostedNFSServer):
    def _getExportsLine(self):
        exportLines = []
        for path in self.paths:
            exportLines.append(
                '%s *(sync,rw,no_root_squash,no_subtree_check)' % path)
        return '\n'.join(exportLines)

    def _getCommandsToPrepareSharedDirectory(self):
        return ["mkdir -p %s" % path for path in self.paths]

    def getStorageRepositoryClass(self):
        return xenrt.lib.xenserver.NFSStorageRepository

    def prepareDomZero(self, host):
        pass


class _LinuxHostedNFSv4Server(_AbstractLinuxHostedNFSServer):
    def _getExportsLine(self):
        return '/nfsv4-root *(sync,rw,no_root_squash,no_subtree_check,fsid=0)'

    def _getCommandsToPrepareSharedDirectory(self):
        prepareCommands = []
        for path in self.paths:
            prepareCommands += [
                "mkdir -p /nfsv4-root",
                "mkdir -p /nfsv4-root%s" % path,
                "chmod o+w /nfsv4-root%s" % path,
            ]
        return prepareCommands

    def getStorageRepositoryClass(self):
        return xenrt.lib.xenserver.NFSv4StorageRepository

    def hostNameCouldBeResolved(self, host):
        return 0 == host.execdom0('ping -c 1 -W1 $(hostname)', retval='code')

    def prepareDomZero(self, host):
        if not self.hostNameCouldBeResolved(host):
            host.execdom0(
                'echo "search xenrt.xs.citrite.net" >> /etc/resolv.conf')

        if not self.hostNameCouldBeResolved(host):
            raise xenrt.XRTError(
                'NFSv4 expects hostname to resolve to an address')


class _LinuxHostedNFSV4ISOServer(_LinuxHostedNFSv4Server):
    def getStorageRepositoryClass(self):
        return xenrt.lib.xenserver.NFSv4ISOStorageRepository
        
def linuxBasedNFSServer(revision, paths):
    if revision == 3:
        return _LinuxHostedNFSv3Server(paths)
    elif revision == 4:
        return _LinuxHostedNFSv4Server(paths)
    else:
        raise ValueError('Invalid value for revision')
        
def linuxBasedNFSISOServer(revision, paths):
        """ This returns an NFS v4 ISO server"""
        if revision == 4:
            return _LinuxHostedNFSV4ISOServer(paths)
        else:
            raise ValueError("Unsupported Version")

class TC7804(xenrt.TestCase):
    """Check that installing PV drivers doesn't cause a disk to go offline."""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.guest = None
        self.host = None
        self.distro = "ws08sp2-x86"
        self.memory = xenrt.KILO
        # Default to a 10Gb disk.
        self.disksize = 10

    def getOfflineDisks(self):
        data = self.guest.xmlrpcExec("echo list disk | diskpart",
                                      returndata=True)
        status = re.findall("Disk ([0-9])\W+(\w+)", data)
        return filter(lambda (a,b):b == 'Offline', status)

    def run(self, arglist):
        self.host = self.getDefaultHost()
        gdef = {}
        gdef["host"] = self.host
        gdef["guestname"] = xenrt.randomGuestName()
        gdef["distro"] = self.distro
        gdef["disks"] = [(1, self.disksize, True)]
        gdef["vifs"] = [(0, None, xenrt.randomMAC(), None)]
        gdef["memory"] = self.memory
        self.guest = xenrt.lib.xenserver.guest.createVM(**gdef)
        self.getLogsFrom(self.guest)
        # Check disk is there and accessible.
        offline = self.getOfflineDisks()
        if offline:
            raise xenrt.XRTFailure("Found offline disk before installing "
                                   "PV drivers. (%s)" % (offline))
        # Install PV drivers.
        self.guest.installDrivers()
        # Check disk again.
        offline = self.getOfflineDisks()
        if offline:
            raise xenrt.XRTFailure("Found offline disk after installing "
                                   "PV drivers. (%s)" % (offline))

    def postRun(self):
        try:
            self.guest.shutdown(force=True)
        except:
            pass
        try:
            self.guest.uninstall()
        except:
            pass

class SRSanityTestTemplate(xenrt.TestCase):
    """SR Sanity Test Template"""

    SKIP_VDI_CREATE = False
    TARGET_USE_EXTRA_VBD = False
    TARGET_USE_EXTRA_VBD_SIZE = 32768
    CHECK_FOR_OPEN_ISCSI = False
    NFS_VERSION = 3

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.guest = None
        self.sruuids = []

    def run(self,arglist):

        host = None
        try:
            # Get a host to use
            host = self.getDefaultHost()
            self.host = host

            if self.CHECK_FOR_OPEN_ISCSI:
                # Check the host hasn't got any open iSCSI sessions (CA-74961)
                
                # This can now return 21 for "no active sessions" (CA-115497)
                if 21 != host.execdom0("iscsiadm -m session", retval="code"):
                    data = host.execdom0("iscsiadm -m session")
                    if not "No active sessions" in data:
                        xenrt.TEC().warning("Found active iSCSI sessions - rebooting host...")
                        host.reboot(timeout=600)

            # Install a linux guest to serve the SR from
            # Disallow kernel update as this isn't necessary and
            # won't be possible if we don't have the source
            # for the kernel in /usr/src on the VM.
            self.guest = host.createGenericLinuxGuest(allowUpdateKernel=False)
            self.getLogsFrom(self.guest)

            if self.TARGET_USE_EXTRA_VBD:
                targetuuid = self.host.createVDI(self.TARGET_USE_EXTRA_VBD_SIZE*xenrt.MEGA)
                targetdev = self.guest.createDisk(vdiuuid=targetuuid)
                targetdev = self.host.parseListForOtherParam(\
                    "vbd-list",
                    "vm-uuid",
                    self.guest.getUUID(),
                    "device",
                    "userdevice=%s" % (targetdev))
                mountpoint = "/srexport"
                self.guest.execguest("mkdir -p %s" % (mountpoint))
                self.guest.execguest("mkfs.ext2 /dev/%s" % (targetdev))
                self.guest.execguest("mount /dev/%s %s" % (targetdev, mountpoint))
                self.guest.execguest("echo /dev/%s %s ext2 defaults 0 0 >> /etc/fstab" % (targetdev, mountpoint))

        except xenrt.XRTFailure, e:
            # Not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        # Create the SR (this bit gets done by child classes)
        ret = self.createSR(host,self.guest)
        if type(ret) == type(""):
            sruuids = [ret]
        else:
            sruuids = ret
        if not sruuids or len(sruuids) == 0:
            # Couldn't create SR, so we skip the test
            return
        self.sruuids.extend(sruuids)
        self.checkSRs()
        self.teardown()

    def checkSRs(self):
        """Make sure we can create VDIs in each of the SRs in self.sruuids"""
        cli = self.host.getCLIInstance()
        cli.execute("sr-list", "params=all")
        if not self.SKIP_VDI_CREATE:
            for sruuid  in self.sruuids:
                # Create a 256M VDI on the SR
                args = []
                args.append("name-label='XenRT Test VDI on %s'" % (sruuid))
                args.append("sr-uuid=%s" % (sruuid))
                args.append("virtual-size=268435456") # 256M
                args.append("type=user")
                vdi = cli.execute("vdi-create", string.join(args), strip=True)
                
                # Now delete it
                cli.execute("vdi-destroy","uuid=%s" % (vdi))

    def teardown(self):
        pass

    def postRun(self):
        # Cleanup
        for sruuid in self.sruuids:
            # We created an SR, lets try and forget it
            try:
                self.host.forgetSR(sruuid)
            except:
                xenrt.TEC().warning("Exception while forgetting SR on host")
        # Get rid of the guest
        if self.guest:
            try:
                try:
                    self.guest.shutdown(force=True)
                except:
                    pass
                self.guest.poll("DOWN", 120, level=xenrt.RC_ERROR)
                self.guest.uninstall()
            except:
                xenrt.TEC().warning("Exception while uninstalling temp guest")
 
    def createSR(self,host,guest):
        raise xenrt.XRTError("Unimplemented")

class NFSSRSanityTest(SRSanityTestTemplate):
    """NFS SR Sanity Test"""

    SRNAME = "test-nfs"
    SR_TYPE = "nfs"

    def createSR(self,host,guest):
        nfsServer = linuxBasedNFSServer(self.NFS_VERSION, ['/sr'])

        nfsServer.createNFSExportOnGuest(guest)

        nfsServer.prepareDomZero(host)

        # CA-21630 Wait a short delay to let the nfs server properly start
        time.sleep(10)

        # Create the SR on the host
        if self.SR_TYPE == "nfs":
            sr = nfsServer.getStorageRepositoryClass()(host, self.SRNAME)
            if not xenrt.TEC().lookup("NFSSR_WITH_NOSUBDIR", None):
                sr.create(guest.getIP(),"/sr")
            else:
                sr.create(guest.getIP(),"/sr", nosubdir=True) # NFS SR with no sub directory sanity test
                
        elif self.SR_TYPE == "file":
            sr = xenrt.lib.xenserver.FileStorageRepositoryNFS(host, self.SRNAME)
            sr.create(guest.getIP(),"/sr")

        return sr.uuid
        
class NFSISOSRSanityTest(SRSanityTestTemplate):
    """NFS ISO SR Sanity Test"""

    SRNAME = "test-nfs-iso"

    def createSR(self,host,guest):
        nfsIsoServer = linuxBasedNFSISOServer(self.NFS_VERSION, ['/sr'])

        nfsIsoServer.createNFSExportOnGuest(guest)

        nfsIsoServer.prepareDomZero(host)

        # CA-21630 Wait a short delay to let the nfs server properly start
        time.sleep(10)

        # Create the SR on the host
        sr = nfsIsoServer.getStorageRepositoryClass()(host, self.SRNAME)
        sr.create(guest.getIP(),"/sr")
                
        return sr.uuid
        
    def teardown(self):
        sruuid = self.sruuids[0]
        self.host.destroySR(sruuid)
        if sruuid in self.host.minimalList("sr-list"):
            raise xenrt.XRTFailure("SR still exists after destroy")
        self.sruuids.remove(sruuid)

class TCNFSISOSrCreationAndDeletion(NFSISOSRSanityTest):
    """Test the creation and destruction of NFSv4 ISO SR"""
    NFS_VERSION = 4
    
class TC6824(NFSSRSanityTest):
    SRNAME = "test-nfs"
    SR_TYPE = "nfs"


class TC21934(NFSSRSanityTest):
    SRNAME = "test-nfs"
    SR_TYPE = "nfs"
    NFS_VERSION = 4


class TC20940(NFSSRSanityTest):
    """File SR Sanity Test"""
    
    SR_TYPE="file"

class TC10626(NFSSRSanityTest):
    """Creation, operation and destruction of a NFS SR with a name containing non-ASCII characters"""

    NEW_SRNAME =  u"NFS\u03b1booo2342\u03b1 SR"

    def createSR(self,host,guest):
        sruuid = NFSSRSanityTest.createSR(self, host, guest)
        try:
            session = host.getAPISession()
            try:
                xapi = session.xenapi
                srref = xapi.SR.get_by_uuid(sruuid)
                xapi.SR.set_name_label(srref, self.NEW_SRNAME)
            finally:
                host.logoutAPISession(session)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            try:
                host.forgetSR(sruuid)
            except:
                xenrt.TEC().warning("Exception while forgetting SR on host")
            raise e
        return sruuid

    def teardown(self):
        sruuid = self.sruuids[0]
        self.host.destroySR(sruuid)
        if sruuid in self.host.minimalList("sr-list"):
            raise xenrt.XRTFailure("SR still exists after destroy")
        self.sruuids.remove(sruuid)

class TC20937(TC10626):
    """Creation, operation and destruction of a file SR with a name containing non-ASCII characters"""

    SR_TYPE = "file"


class TC23334(TC10626):
    """Creation, operation and destruction of a file SR with a name containing non-ASCII characters"""

    NFS_VERSION = 4


class TC20948(NFSSRSanityTest):
    """NFS SR (with no sub directory) Sanity Test"""

    def prepare(self,arglist):
        xenrt.TEC().config.setVariable("NFSSR_WITH_NOSUBDIR", "yes")

class TCNFS4NoSubDir(NFSSRSanityTest):
    """NFS 4 SR (with no sub directory) Sanity Test"""
    NFS_VERSION = 4
    
    def prepare(self,arglist):
        xenrt.TEC().config.setVariable("NFSSR_WITH_NOSUBDIR", "yes")

class TC20949(SRSanityTestTemplate):
    """Co-existence of multiple NFS SRs with no sub directory on the same NFS path"""

    def createSR(self,host,guest):
        server, path = xenrt.ExternalNFSShare().getMount().split(":")

        # Create a NFS SR with no sub directory.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr-withnosubdir-1")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)

        # Create another NFS SR with no sub directory on the same NFS path.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr-withnosubdir-2")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)
        
        return self.sruuids

class NFSSRSanityTestTemplate(SRSanityTestTemplate):
    """Template for NFS Sr"""
    
    def verifyVersion(self, host, sruuid, version):
        mounts = []
        if version == "3":
            mounts = host.execdom0("mount -t nfs")
        elif version == "4":
            mounts = host.execdom0("mount -t nfs4")
        
        if not mounts:
            raise xenrt.XRTError("Not an NFS SR")
        
        lines = mounts.split("\n")
        found = False
        for line in lines:
            if sruuid in line:
                found = True
        if not found:
            raise xenrt.XRTError("Incorrect NFS Version")

class TCCoexistenceOfNFS4NoSubDirs(NFSSRSanityTestTemplate):
    """Co-existence of multiple NFS SRs (version 4) with no sub directory on the same NFS path"""
     
    def createSR(self,host,guest):
        server, path = xenrt.ExternalNFSShare(version="4").getMount().split(":")

        # Create a NFS SR with no sub directory.
        nfsSR = xenrt.lib.xenserver.NFSv4StorageRepository(host, "nfssr-withnosubdir-1")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)
       
        self.verifyVersion(host, nfsSR.uuid, "4")
        
        # Create another NFS SR with no sub directory on the same NFS path.
        nfsSR = xenrt.lib.xenserver.NFSv4StorageRepository(host, "nfssr-withnosubdir-2")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)
        
        self.verifyVersion(host, nfsSR.uuid, "4")
        
        return self.sruuids

class TC20950(SRSanityTestTemplate):
    """Co-existance of NFS SR with no sub directory and classic NFS SR on the same NFS path"""

    def createSR(self,host,guest):
        server, path = xenrt.ExternalNFSShare().getMount().split(":")

        # Create a NFS SR with no sub directory.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr-withnosubdir-3")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)
        
        # Create a classic NFS SR on the same path.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr-classic-1")
        nfsSR.create(server, path)
        self.sruuids.append(nfsSR.uuid)        

        return self.sruuids
        
class TCCoexitenceNFS4NoSubDirClassic(NFSSRSanityTestTemplate):
    """Co-existence of NFS SR v4 with no sub directory and classic NFS SR v4 on the same NFS path"""

    def createSR(self,host,guest):
        server, path = xenrt.ExternalNFSShare(version="4").getMount().split(":")

        # Create a NFS SR with no sub directory.
        nfsSR = xenrt.lib.xenserver.NFSv4StorageRepository(host, "nfssr-withnosubdir-3")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)
        
        self.verifyVersion(host, nfsSR.uuid, "4")

        # Create a classic NFS SR on the same path.
        nfsSR = xenrt.lib.xenserver.NFSv4StorageRepository(host, "nfssr-classic-1")
        nfsSR.create(server, path)
        self.sruuids.append(nfsSR.uuid)

        self.verifyVersion(host, nfsSR.uuid, "4")

        return self.sruuids
        
class TCCoexistenceNFS4AndNFSv3(NFSSRSanityTestTemplate):
    """Co-existence of NFS SR v4 and NFS SR v3 on the same NFS path"""

    def createSR(self,host,guest):
        server, path = xenrt.ExternalNFSShare(version="4").getMount().split(":")

        # Create a NFS v4 SR with no sub directory.
        nfsSR = xenrt.lib.xenserver.NFSv4StorageRepository(host, "nfssr-v4")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)
        
        self.verifyVersion(host, nfsSR.uuid, "4")

        # Create a v3 SR with no sub directory.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr-v3")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)

        self.verifyVersion(host, nfsSR.uuid, "3")

        return self.sruuids

class TC20951(SRSanityTestTemplate):
    """Co-existance of NFS SR with no sub directory and file SR on the same NFS path"""

    def createSR(self,host,guest):
        server, path = xenrt.ExternalNFSShare().getMount().split(":")

        # Create a NFS SR with no sub directory.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr-withnosubdir-4")
        nfsSR.create(server, path, nosubdir=True)
        self.sruuids.append(nfsSR.uuid)        

        # Create a file SR on the same NFS path.
        fileSR = xenrt.lib.xenserver.FileStorageRepositoryNFS(host, "nfssr-filesr-1")
        fileSR.create(server, path)
        self.sruuids.append(fileSR.uuid)        

        return self.sruuids

class TC20952(SRSanityTestTemplate):
    """Co-existance of Classic NFS SR and file SR on the same NFS path"""

    def createSR(self,host,guest):
        server, path = xenrt.ExternalNFSShare().getMount().split(":")

        # Create a classic NFS SR.
        nfsSR = xenrt.lib.xenserver.NFSStorageRepository(host, "nfssr-classic-2")
        nfsSR.create(server, path)
        self.sruuids.append(nfsSR.uuid)        

        # Create a file SR on the same NFS path.
        fileSR = xenrt.lib.xenserver.FileStorageRepositoryNFS(host, "nfssr-filesr-2")
        fileSR.create(server, path)
        self.sruuids.append(fileSR.uuid)

        return self.sruuids

class TC6825(SRSanityTestTemplate):
    """ISCSI SR Sanity Test"""

    def createSR(self,host,guest):
        try:
            # Prepare guest to be an iSCSI target
            iqn = guest.installLinuxISCSITarget()
            if self.TARGET_USE_EXTRA_VBD:
                guest.createISCSITargetLun(0, xenrt.KILO, dir="/srexport/")
            else:
                guest.createISCSITargetLun(0, xenrt.KILO)
        except xenrt.XRTFailure, e:
            # Not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        # CA-21630 Wait a short delay to let the iSCSI target properly start
        time.sleep(10)

        # Set up the SR on the host and plug the pbd etc
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(host,"test-iscsi")
        lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" % 
                                      (iqn, guest.getIP()))
        # Find out the SCSIID
        cli = host.getCLIInstance()
        args = []
        args.append("type=lvmoiscsi")
        args.append("device-config:target=%s" % (lun.getServer()))
        args.append("device-config:targetIQN=%s" % (lun.getTargetName()))
        args.append("device-config:LUNid=0")
        failProbe = False
        xenrt.TEC().logverbose("Finding SCSIID using sr-probe")
        try:
            cli.execute("sr-probe", string.join(args))
            failProbe = True
        except xenrt.XRTFailure, e:
            # Split away the stuff before the <?xml
            split = e.data.split("<?",1)
            if len(split) != 2:
                raise xenrt.XRTFailure("Couldn't find XML output from "
                                       "sr-probe command")
            # Parse the XML and find the SCSIid
            dom = xml.dom.minidom.parseString("<?" + split[1])
            luns = dom.getElementsByTagName("LUN")
            found = False
            for l in luns:
                lids = l.getElementsByTagName("LUNid")
                if len(lids) == 0:
                    continue
                lunid = int(lids[0].childNodes[0].data.strip())
                if lunid == lun.getLunID():
                    ids = l.getElementsByTagName("SCSIid")
                    if len(ids) == 0:
                        raise xenrt.XRTFailure("Couldn't find SCSIid for "
                                               "lun %u in XML output" %
                                               (lunid))
                    lun.setID(ids[0].childNodes[0].data.strip())
                    found = True
                    break
            if not found:
                raise xenrt.XRTFailure("Couldn't find lun in XML output")

        if failProbe:
            raise xenrt.XRTFailure("sr-probe unexpectedly returned "
                                   "successfully when attempting to "
                                   "find SCSIID")

        # Check we can probe it successfully (CA-29044)
        args.append("device-config:SCSIid=\"%s\"" % (lun.getID()))           
        xenrt.TEC().logverbose("Checking sr-probe with SCSIid")
        cli.execute("sr-probe", string.join(args))

        # Create it
        sr.create(lun,subtype="lvm")

        return sr.uuid

class TC7366(SRSanityTestTemplate):
    """Create an iSCSI SR on a LUN other then LUN ID 0"""
    CHECK_FOR_OPEN_ISCSI = True

    def createSR(self, host, guest, thinProv=False):
        iqn = None
        try:
            # Prepare guest to be an iSCSI target
            iqn = guest.installLinuxISCSITarget()
            if self.TARGET_USE_EXTRA_VBD:
                guest.createISCSITargetLun(0, 128, dir="/srexport/")
                guest.createISCSITargetLun(1, 1024, dir="/srexport/")
            else:
                guest.createISCSITargetLun(0, 128)
                guest.createISCSITargetLun(1, 1024)
        except xenrt.XRTFailure, e:
            # Not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        # Set up the SR on the host and plug the pbd etc
        host.setIQN("xenrt-test-iqn-TC7366")
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(host, "test-iscsi", thinProv)
        lun = xenrt.ISCSIIndividualLun(None,
                                       1,
                                       server=guest.getIP(),
                                       targetname=iqn)
        sr.create(lun,subtype="lvm",findSCSIID=True,noiqnset=True)
        time.sleep(60)
        
        # Make sure it's the 1024MB LUN we used
        host.execdom0("xe sr-scan uuid=%s" % sr.uuid)
        size = sr.physicalSizeMB()
        if size < 950:
            raise xenrt.XRTFailure("The SR was only %uMB in size. The LUN "
                                   "was 1024MB" % (size))
        return sr.uuid

class TC7367(SRSanityTestTemplate):
    """Create two iSCSI SRs on LUNs on the same target"""

    NUM_LUNS = 2
    LUN_SIZE = 1024
    LUN_SIZES = [512, 1024]
    CHECK_FOR_OPEN_ISCSI = True

    def createSR(self, host, guest, thinProv=False):
        iqn = None
        try:
            # Prepare guest to be an iSCSI target
            iqn = guest.installLinuxISCSITarget()
            for i in range(self.NUM_LUNS):
                if len(self.LUN_SIZES) > i:
                    size = self.LUN_SIZES[i]
                else:
                    size = self.LUN_SIZE
                if self.TARGET_USE_EXTRA_VBD:
                    guest.createISCSITargetLun(i, size, dir="/srexport/")
                else:
                    guest.createISCSITargetLun(i, size)
            
        except xenrt.XRTFailure, e:
            # Not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        # Set up the SR on the host
        host.setIQN("xenrt-test-iqn-TC7367")

        # Probe the target and check the LUNs were all found
        try:
            args = ["type=lvmoiscsi"]
            args.append("device-config:target=%s" % (guest.getIP()))
            args.append("device-config:targetIQN=%s" % (iqn))
            cli = host.getCLIInstance()            
            data = cli.execute("sr-probe", string.join(args)).strip()
        except xenrt.XRTFailure, e:
            # Split away the stuff before the <?xml
            split = e.data.split("<?",1)
            if len(split) != 2:
                raise xenrt.XRTFailure("Couldn't find XML output from "
                                       "sr-probe command")
            data = "<?" + split[1]
        # Parse the XML and check each LUN
        dom = xml.dom.minidom.parseString(data)
        luns = dom.getElementsByTagName("LUN")
        if len(luns) != self.NUM_LUNS:
            raise xenrt.XRTFailure(\
                "sr-probe returned the wrong number of LUNs",
                "Wanted %u, got %u" % (self.NUM_LUNS, len(luns)))
        missing = map(lambda x:1, range(self.NUM_LUNS))
        errors = []
        for l in luns:
            
            lids = l.getElementsByTagName("LUNid")
            if len(lids) == 0:
                errors.append("No LUNid found for a LUN")
                continue
            lunid = int(lids[0].childNodes[0].data.strip())
            
            ids = l.getElementsByTagName("SCSIid")
            if len(ids) == 0:
                errors.append("No SCSIid found for LUN %u" % (lunid))
                continue
            scsiid = ids[0].childNodes[0].data.strip()
            
            sizes = l.getElementsByTagName("size")
            if len(sizes) == 0:
                errors.append("No size found for LUN %u" % (lunid))
                continue
            size = int(sizes[0].childNodes[0].data.strip())

            xenrt.TEC().logverbose("Found LUNid %u, ID %s, size %u" %
                                   (lunid, scsiid, size))

            if lunid >= self.NUM_LUNS or lunid < 0:
                errors.append("LUNid %u is out of the expected range" %
                              (lunid))
                continue
            missing[lunid] = 0

            if len(self.LUN_SIZES) > lunid:
                expsize = self.LUN_SIZES[lunid]
            else:
                expsize = self.LUN_SIZE
            err = float(abs(size/xenrt.MEGA - expsize))/float(expsize)
            if err > 0.1:
                errors.append("LUNid %u size isn't as expected" % (lunid),
                              "Size %u, expected %u" % (size/xenrt.MEGA, expsize))
                continue

        if len(errors) > 0:
            for error in errors:
                xenrt.TEC().logverbose("ERROR in sr-probe output: %s" %
                                       (error))
            raise xenrt.XRTFailure("Error(s) found in sr-probe output")

        # Create the SRs
        srs = []
        for lunid in range(self.NUM_LUNS):
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(\
                host, "test-iscsi%u" % (lunid), thinProv)
            lun = xenrt.ISCSIIndividualLun(None,
                                           lunid,
                                           server=guest.getIP(),
                                           targetname=iqn)
            sr.create(lun,subtype="lvm",findSCSIID=True,noiqnset=True)
            srs.append(sr)
            time.sleep(60)
        
        # Check we used the right LUNs
        for i in range(self.NUM_LUNS):
            if len(self.LUN_SIZES) > i:
                expsize = self.LUN_SIZES[i]
            else:
                expsize = self.LUN_SIZE
            size = srs[i].physicalSizeMB()
            err = float(abs(size - expsize))/float(expsize)
            if err > 0.1:
                raise xenrt.XRTFailure("The SR based on LUN %u is much "
                                       "different in size than the LUN" % (i),
                                       "SR size %u, expected %u" %
                                       (size, expsize))
        return map(lambda x:x.uuid, srs)

    def teardown(self):
        """Remove the first of the two SRs and check the second still operates.
        """
        sruuid = self.sruuids[0]
        self.host.forgetSR(sruuid)
        if sruuid in self.host.minimalList("sr-list"):
            raise xenrt.XRTFailure("SR on LUN0 still exists after forget")
        self.sruuids.remove(sruuid)
        if self.sruuids[0] not in self.host.minimalList("sr-list"):
            raise xenrt.XRTFailure("SR on LUN1 missing after forget of the SR "
                                   "on LUN0")
        self.checkSRs()

class TC27042(TC7366):
    """Create a thin provisioning iSCSI SR on a LUN other then LUN ID 0"""
    CHECK_FOR_OPEN_ISCSI = True

    def createSR(self,host,guest):
        return super(TC27042, self).createSR(host, guest, True)

class TC27043(TC7367):
    """Create two thin provisioning iSCSI SRs on LUNs on the same target"""

    def createSR(self,host,guest):
        return super(TC27043, self).createSR(host, guest, True)

class TC9085(TC7367):
    """Create LVMoISCSI SRs on 64 LUNs having first probed the target"""
    NUM_LUNS = 64
    LUN_SIZE = 256
    LUN_SIZES = []
    SKIP_VDI_CREATE = True
    TARGET_USE_EXTRA_VBD = True
    
class TC7368(SRSanityTestTemplate):
    """Create two NFS SRs on the same NFS server"""

    def createSR(self,host,guest):
        nfsServer = linuxBasedNFSServer(self.NFS_VERSION, ['/sr0', '/sr1'])

        nfsServer.createNFSExportOnGuest(guest)

        nfsServer.prepareDomZero(host)

        # Create the SRs on the host
        sr0 = nfsServer.getStorageRepositoryClass()(host,"test-nfs0")
        sr0.create(guest.getIP(),"/sr0")
        sr1 = nfsServer.getStorageRepositoryClass()(host,"test-nfs1")
        sr1.create(guest.getIP(),"/sr1")

        return [sr0.uuid, sr1.uuid]

    def teardown(self):
        """Remove the first of the two SRs and check the second still operates.
        """
        sruuid = self.sruuids[0]
        self.host.forgetSR(sruuid)
        if sruuid in self.host.minimalList("sr-list"):
            raise xenrt.XRTFailure("First SR still exists after forget")
        self.sruuids.remove(sruuid)
        if self.sruuids[0] not in self.host.minimalList("sr-list"):
            raise xenrt.XRTFailure("Second SR missing after forget of the "
                                   "first SR")
        self.checkSRs()


class TC23336(TC7368):

    NFS_VERSION = 4


class TC7369(SRSanityTestTemplate):
    """Create an iSCSI SR on a target requiring CHAP authentication"""

    user = "myuser"
    password = "TC7369passwd"
    outgoingUser = None
    outgoingPassword = None

    def createSR(self,host,guest):
        iqn = guest.installLinuxISCSITarget(user=self.user, password=self.password, outgoingUser=self.outgoingUser, outgoingPassword=self.outgoingPassword)
        
        if self.TARGET_USE_EXTRA_VBD:
            guest.createISCSITargetLun(0, xenrt.KILO, dir="/srexport/")
        else:
            guest.createISCSITargetLun(0, xenrt.KILO)

        # Set up the SR on the host and plug the pbd etc
        srx = xenrt.lib.xenserver.ISCSIStorageRepository(host,"test-iscsi")
        lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" % (iqn, guest.getIP()))
        try:
            srx.create(lun, subtype="lvm", findSCSIID=True)
        except xenrt.XRTFailure, e:
            pass
        else:
            raise xenrt.XRTFailure("Was able to create iSCSI SR without CHAP")

        sr = xenrt.lib.xenserver.ISCSIStorageRepository(host,"test-iscsi")
        lun = xenrt.ISCSILunSpecified("xenrt-test/%s/%s" % (iqn, guest.getIP()))
        lun.setCHAP(self.user, self.password)
        
        if self.outgoingUser and self.outgoingPassword:
            
            lun.setOutgoingCHAP("wrong user", "wrong password")

            try:
                srx.create(lun, subtype="lvm", findSCSIID=True)
            except xenrt.XRTFailure, e:
                pass
            else:
                raise xenrt.XRTFailure("Was able to create iSCSI SR without mutual CHAP")
                
            lun.setOutgoingCHAP(self.outgoingUser, self.outgoingPassword)
        
        sr.create(lun,subtype="lvm", findSCSIID=True)

        return sr.uuid

class TC12818(TC7369):
    """Create an iSCSI SR on a target requiring mutual CHAP authentication"""
    outgoingUser = "myoutgoinguser"
    outgoingPassword = "TC12818outgoingpasswd"

class TC6846(xenrt.TestCase):
    """VHD parent-child handling with vm-clone and delete"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.guestsToClean = []
        self.sr = None

    def run(self,arglist):

        host = None
        guest = None
        clone = None
        try:
            # Get a host to use
            host = self.getDefaultHost()
            self.host = host

            # look for VHD SR
            sr = None
            try:
                sr = host.getSRs(type="ext")[0]
            except:
                pass

            if not sr:
                try:
                    sr = host.getSRs(type="nfs")[0]
                except:
                    raise xenrt.XRTError("No VHD repositories found")

            self.sr = sr

            # Install a linux guest to clone
            guest = host.createGenericLinuxGuest(sr=sr)
            self.guestsToClean.append(guest)
            guest.preCloneTailor()
            guest.shutdown()

            clone = guest.cloneVM()
            self.guestsToClean.append(clone)
        except xenrt.XRTFailure, e:
            # Not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        # Verify that we have the correct parent + 2 child VHDs
        guest_vdis = []
        diskdevs = guest.listDiskDevices()
        clone_vdis = []
        parent_uuids = {}
        for diskdev in diskdevs:
            guest_vdi = guest.getDiskVDIUUID(diskdev)
            guest_vdis.append(guest_vdi)
            if not self.checkVHDExists(guest_vdi):
                raise xenrt.XRTFailure("Cannot find VHD for vdi %s" % 
                                       (guest_vdi))
            guest_parent = self.getParent(guest_vdi)
            clone_vdi = clone.getDiskVDIUUID(diskdev)
            clone_vdis.append(clone_vdi)
            if not self.checkVHDExists(clone_vdi):
                raise xenrt.XRTFailure("Cannot find VHD for vdi %s" %
                                       (clone_vdi))
            clone_parent = self.getParent(clone_vdi)
            if guest_parent != clone_parent:
                raise xenrt.XRTFailure("Parent of clone device %s (%s) does "
                                       "not match parent of original (%s)" %
                                       (diskdev,clone_parent,guest_parent))
            parent_uuids[clone_vdi] = clone_parent
            if not self.checkVHDExists(clone_parent):
                raise xenrt.XRTFailure("Cannot find parent VHD for device "
                                       "%s (%s.vhd)" % (diskdev,clone_parent))

        # Uninstall the original
        guest.uninstall()
        self.guestsToClean.remove(guest)

        # Wait a bit for GC
        time.sleep(30)

        # Verify that we still have the parent + 1 child VHD
        for vdi in guest_vdis:
            # Check they don't exist
            if self.checkVHDExists(vdi):
                raise xenrt.XRTFailure("Original VHD %s.vhd still exists after "
                                       "uninstall of guest" % (vdi))
        for vdi in clone_vdis:
            if not self.checkVHDExists(vdi):
                raise xenrt.XRTFailure("VHD of clone %s.vhd has been deleted" % 
                                       (vdi))
            clone_parent = self.getParent(vdi)
            if clone_parent != parent_uuids[vdi]:
                raise xenrt.XRTFailure("Parent of clone VDI changed from %s to "
                                       "%s" % (parent_uuids[vdi],clone_parent))
            if not self.checkVHDExists(clone_parent):
                raise xenrt.XRTFailure("Parent VHD %s.vhd has been deleted" %
                                       (clone_parent))

        # Try starting the clone
        clone.start()
        clone.shutdown()

        # Uninstall the clone
        clone.uninstall()
        self.guestsToClean.remove(clone)
        
        # Wait a bit for GC
        time.sleep(30)

        # Verify that both the parent and child VHD have been deleted
        for vdi in clone_vdis:
            # Check they don't exist
            if self.checkVHDExists(vdi):
                raise xenrt.XRTFailure("Cloned VHD %s.vhd still exists after "
                                       "uninstall of clone" % (vdi))

        for uuid in parent_uuids.values():
            if self.checkVHDExists(uuid):
                raise xenrt.XRTFailure("Parent VHD %s.vhd was not deleted "
                                       "after all children deleted" % (uuid))

    def getParent(self,uuid):
        # Return the parent VHD of this VDI
        # Temporary nasty way of doing it (xapi currently isn't able to output
        # the value!)
        data = self.host.execdom0("td-util query vhd -p "
                                  "/var/run/sr-mount/%s/%s.vhd" % 
                                  (self.sr,uuid)).strip()
        m = re.match(".*/([a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12})\.vhd$",data)
        if m:
            return m.group(1)

    def checkVHDExists(self,uuid):
        # Check that the vhd exists
        return (self.host.execdom0("ls /var/run/sr-mount/%s/%s.vhd" % (self.sr,
                                                                       uuid),
                                   retval="code") == 0)

    def postRun(self):
        # Cleanup
        for guest in self.guestsToClean:
            try:
                try:
                    guest.shutdown(force=True)
                except:
                    pass
                guest.poll("DOWN", 120, level=xenrt.RC_ERROR)
                guest.uninstall()
            except:
                xenrt.TEC().warning("Exception while uninstalling temp guest")

class TC7482(xenrt.TestCase):
    """vdi-clone using slow copy should not lock the SR"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.cli = None
        self.vdis = []

    def run(self,arglist):

        host = None
        try:
            # Get a host to use
            host = self.getDefaultHost()
            self.host = host

            # look for LVM SR
            sr = None
            try:
                sr = host.getSRs(type="lvm")[0]
            except:
                pass

            if not sr:
                try:
                    sr = host.getSRs(type="lvmoiscsi")[0]
                except:
                    pass
            if not sr:
                try:
                    sr = host.getSRs(type="lvmohba")[0]
                except:
                    raise xenrt.XRTError("No LVM SRs found")

            # Create the initial 10G VDI
            cli = host.getCLIInstance()
            self.cli = cli
            args = []
            args.append("name-label=Created by XenRT")
            args.append("sr-uuid=%s" % (sr))
            args.append("virtual-size=%d" % (10 * xenrt.GIGA)) # 10G
            args.append("type=user")
            vdi = cli.execute("vdi-create", string.join(args), strip=True)
            self.vdis.append(vdi)
        except xenrt.XRTFailure, e:
            # Not a failure of the testcase
            raise xenrt.XRTError(e.reason)

        # Start a vdi-clone going (we'll execute it on the host)
        host.execdom0("xe vdi-clone uuid=%s > /tmp/newvdi.xenrt 2>&1 &" % (vdi))
        
        # Give it 10 seconds to make sure it's actually going properly
        time.sleep(10)

        # Attempt to create a small VDI, and time how long it takes
        args = []
        args.append("name-label=Created by XenRT")
        args.append("sr-uuid=%s" % (sr))
        args.append("virtual-size=%d" % (100 * xenrt.MEGA)) # 100M
        args.append("type=user")
        st = xenrt.util.timenow()
        smallvdi = cli.execute("vdi-create", string.join(args), strip=True)
        self.vdis.append(smallvdi)
        ft = xenrt.util.timenow()
        if (ft - st) > 40:
            raise xenrt.XRTFailure("vdi-create of small VDI appears locked by "
                                   "vdi-clone of large VDI (CA-14936)")

        # Check the vdi-clone is still going
        if host.execdom0("ps -ef | grep [v]di-clone",retval="code") > 0:
            # Check if we've got output (might just be the command finished)
            data = host.execdom0("touch /tmp/newvdi.xenrt && "
                                 "cat /tmp/newvdi.xenrt")
            if not xenrt.isUUID(data.strip()):
                raise xenrt.XRTFailure("vdi-clone of large VDI apparently "
                                       "interrupted by vdi-create of small VDI")
            else:
                self.vdis.append(data.strip())
                # The vdi-clone has finished, but it presumably did it while we
                # were waiting for vdi-create to complete...
                raise xenrt.XRTError("vdi-clone finished too early, test "
                                     "inconclusive")
        else:
            # Wait for it to finish (with a timeout)
            st = xenrt.util.timenow()
            while True:
                if (xenrt.util.timenow() - st) > 1200:
                    raise xenrt.XRTError("vdi-clone not finished after 20 mins")

                if host.execdom0("ps -ef | grep [v]di-clone",retval="code") > 0:
                    break
                time.sleep(10)
            # Find out the UUID
            data = host.execdom0("touch /tmp/newvdi.xenrt && "
                                 "cat /tmp/newvdi.xenrt")
            if xenrt.isUUID(data.strip()):
                self.vdis.append(data.strip()) 

    def postRun(self):
        # Cleanup any VDIs
        if not self.cli:
            return
        for vdi in self.vdis:
            try:
                self.cli.execute("vdi-destroy","uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception attempting to destroy VDI %s" % (vdi))

class _TC8122(xenrt.TestCase):
    """Base class for VHD chain limit TCs"""
    LENGTH = 30

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.host = None
        self.vdis = []
        self.sr = None

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        # Prepare the SR
        self.prepareSR()
        # Write out a mkfs script
        self.host.execdom0("echo '/sbin/mkfs.ext3 /dev/${DEVICE}' > "
                           "/tmp/mkfs.sh")
        self.host.execdom0("chmod u+x /tmp/mkfs.sh")

    def prepareSR(self):
        raise xenrt.XRTError("Unimplemented")

    def run(self, arglist=None):
        cli = self.host.getCLIInstance()
        # Create an initial 100M VDI
        args = []
        args.append("sr-uuid=%s" % (self.sr))
        args.append("virtual-size=%d" % (100 * xenrt.MEGA))
        args.append("type=system")
        args.append("name-label=original")
        uuid = cli.execute("vdi-create", string.join(args),strip=True)
        self.vdis.append(uuid)        
        # Keep cloning it up to (self.LENGTH*2) times or until we hit an error
        cloneCount = 0
        for i in range(self.LENGTH * 2):
            try:
                uuid = cli.execute("vdi-clone","uuid=%s" % (uuid),strip=True)
            except:
                break
            self.vdis.append(uuid)
            # Rename the VDI
            self.host.genParamSet("vdi", uuid, "name-label", 
                                  "clone%u" % (cloneCount + 1))
            # Make a filesystem
            self.host.execdom0("/opt/xensource/debug/with-vdi %s /tmp/mkfs.sh" %
                               (uuid))
            cloneCount += 1
            
        # How many successful clones did we do (this is the chain length)
        if (cloneCount + 1) > self.LENGTH:
            if cloneCount == (self.LENGTH * 2):
                raise xenrt.XRTFailure("No limit found on VHD chain length on "
                                       "ext SR (%u clones created)" % 
                                       (cloneCount))
            raise xenrt.XRTFailure("Able to create a VHD chain of length %u, "
                                   "expected limit %u" % 
                                   (cloneCount,self.LENGTH))
        elif (cloneCount + 1) < self.LENGTH:
            raise xenrt.XRTFailure("Unable to create VHD chain of length %u, "
                                   "managed %u" % (self.LENGTH,cloneCount))

    def postRun(self):
        cli = self.host.getCLIInstance()
        for vdi in self.vdis:
            cli.execute("vdi-destroy uuid=%s" % (vdi))

class TC8122(_TC8122):
    """Ensure that VHD chain limit is enforced on local VHD"""

    def prepareSR(self):
        srs = self.host.getSRs(type="ext", local=True)
        if len(srs) == 0:
            raise xenrt.XRTError("No ext SR found")
        self.sr = srs[0]

class TC8123(_TC8122):
    """Ensure that VHD chain limit is enforced on NFS"""

    def prepareSR(self):
        # Set up an NFS SR
        nfs = self.createExternalNFSShare()
        nfsm = nfs.getMount()
        r = re.search(r"([0-9\.]+):(\S+)", nfsm)
        if not r:
            raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfsm))
        sr = self.getStorageRepositoryClass()(self.host, "NFS SR")
        if not xenrt.TEC().lookup("NFSSR_WITH_NOSUBDIR", None):
            sr.create(r.group(1), r.group(2))
        else:
            sr.create(r.group(1), r.group(2), nosubdir=True) # NFS SR with no sub directory
        self.sr = sr.uuid
        self.host.addSR(sr)

    def getStorageRepositoryClass(self):
        return xenrt.lib.xenserver.NFSStorageRepository

    def createExternalNFSShare(self):
        return xenrt.ExternalNFSShare()
        
class TC23335(TC8123):

    def getStorageRepositoryClass(self):
        return xenrt.lib.xenserver.NFSv4StorageRepository

    def createExternalNFSShare(self):
        return xenrt.ExternalNFSShare(version = "4")


class TC20929(_TC8122):
    """Ensure that VHD chain limit is enforced on filesr"""

    def prepareSR(self):
        # Set up an NFS SR
        nfs = xenrt.ExternalNFSShare()
        nfsm = nfs.getMount()
        r = re.search(r"([0-9\.]+):(\S+)", nfsm)
        if not r:
            raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfsm))
        sr = xenrt.lib.xenserver.FileStorageRepositoryNFS(self.host, "filesr")
        sr.create(r.group(1), r.group(2))
        self.sr = sr.uuid
        self.host.addSR(sr)

class TC6642(xenrt.TestCase):
    """Create read-only and read-write mounts from the same NFS volume."""

    def prepare(self, arglist=None):

        self.host = self.getDefaultHost()
        self.srs = []

    def run(self, arglist=None):

        nfs = xenrt.resources.NFSDirectory()
        isodir = xenrt.command("mktemp -d %s/isoXXXX" % (nfs.path()), strip = True)
        nfsdir = xenrt.command("mktemp -d %s/nfsXXXX" % (nfs.path()), strip = True)

        # Introduce the ISO SR.
        isosr = xenrt.lib.xenserver.ISOStorageRepository(self.host, "isosr")
        server, path = nfs.getHostAndPath(os.path.basename(isodir))
        isosr.create(server, path)
        self.srs.append(isosr)

        # Create the NFS SR.
        nfssr = xenrt.lib.xenserver.NFSStorageRepository(self.host, "nfssr")
        server, path = nfs.getHostAndPath(os.path.basename(nfsdir))
        if not xenrt.TEC().lookup("NFSSR_WITH_NOSUBDIR", None):
            nfssr.create(server, path)
        else:
            nfssr.create(server, path, nosubdir=True) # NFS SR with no sub directory
        self.srs.append(nfssr)

        self.host.execdom0("ls /var/run/sr-mount/%s/" % (isosr.uuid))
        self.host.execdom0("touch /var/run/sr-mount/%s/xenrtwritetest || true" % (isosr.uuid))
        if self.host.execdom0("test -e /var/run/sr-mount/%s/xenrtwritetest" % (isosr.uuid), retval="code") == 0:
            raise xenrt.XRTFailure("Wrote to ISO SR from domain-0.")
        self.host.execdom0("ls /var/run/sr-mount/%s/" % (nfssr.uuid))
        self.host.execdom0("touch /var/run/sr-mount/%s/xenrtwritetest" % (nfssr.uuid))
        if self.host.execdom0("test -e /var/run/sr-mount/%s/xenrtwritetest" % (nfssr.uuid), retval="code") != 0:
            raise xenrt.XRTFailure("Couldn't write to NFS SR from domain-0.")

        for sr in [ nfssr, isosr ]:
            cli = self.host.getCLIInstance()
            args = []
            args.append("name-label=XenRT")
            args.append("sr-uuid=%s" % (sr.uuid))
            args.append("virtual-size=1GiB")
            args.append("type=user")
            failed = False
            try:
                vdiuuid = cli.execute("vdi-create", string.join(args), strip=True)
            except:
                failed = True
            try:
                args = []
                args.append("uuid=%s" % (vdiuuid))
                cli.execute("vdi-destroy", string.join(args))
            except:
                pass

            if self.host.genParamGet("sr", sr.uuid, "type") == "iso":
                if not failed:
                    raise xenrt.XRTFailure("Created VDI on ISO SR.")
            else:
                if failed:
                    raise xenrt.XRTFailure("Couldn't create VDI on NFS SR.")

    def postRun(self):
        for sr in self.srs:
            xenrt.TEC().logverbose("Found SRs %s" % (self.srs))
            try:
                sr.remove()
            except:
                pass

class TC7979(xenrt.TestCase):
    """Ensure NFS disk associations are preserved across host reboot."""

    def prepare(self, arglist=None):

        self.host = self.getDefaultHost()
        nfssr = self.host.getSRs("nfs")[0]

        # Create a VM
        self.guest = self.host.createGenericLinuxGuest(sr=nfssr)
        self.uninstallOnCleanup(self.guest)
        srtype = self.guest.getDiskSRType()
        if srtype != "nfs":
            raise xenrt.XRTError("VM not installed on NFS SR")

        # Attach as many VBDs as possible to the VM
        vbds = self.guest.paramGet("allowed-VBD-devices").split("; ")
        self.disks = []
        for vbd in vbds:
            devno = self.guest.createDisk(sizebytes=xenrt.GIGA,
                                          sruuid=nfssr,
                                          userdevice=vbd)
            time.sleep(30)
            dev = self.host.parseListForOtherParam("vbd-list",
                                                   "vm-uuid",
                                                   self.guest.getUUID(),
                                                   "device",
                                                   "userdevice=%s" %
                                                   (devno))
            
            self.guest.execguest("mkfs.ext2 /dev/%s" % (dev))
            self.guest.execguest("mount /dev/%s /mnt" % (dev))
            self.guest.execguest("touch /mnt/this-is-%s" % (dev))
            self.guest.execguest("umount /mnt")
            
            self.disks.append(dev)

        if len(self.disks) < 6:
            raise xenrt.XRTError("Insufficient attached VBDs to run test")

    def run(self, arglist=None):

        iter = 0
        try:
            while iter < 20:
                xenrt.TEC().logdelimit("loop iteration %u..." % (iter))

                # Reboot the host
                self.host.reboot()
                self.host.waitForEnabled(300, desc="Wait for host to become enabled after reboot")

                # Start the VM
                self.guest.start()

                # Check all VBDs
                for disk in self.disks:
                    self.guest.execguest("mount /dev/%s /mnt" % (disk))
                    try:
                        self.guest.execguest("test -e /mnt/this-is-%s" %
                                             (disk))
                    finally:
                        self.guest.execguest("umount /mnt")    

                # Shut down the VM
                self.guest.shutdown()
                
                iter += 1

        finally:
            xenrt.TEC().comment("%u/20 iterations successful" % (iter))
            
class TC6723(xenrt.TestCase):
    """Basic functionality check of CIFS ISO SR operation"""

    SR_COUNT = 1
    
    def passwordString(self):
        return 'pAssw0rd'

    def prepare(self, arglist=None):

        self.srs = []
        self.srsToRemove = []
        self.host = self.getDefaultHost()

        # Create a Windows VM to be the CIFS server. Use of an existing
        # guest named CIFSSERVER is for test development debug purposes only
        self.guest = xenrt.TEC().registry.guestGet("CIFSSERVER")
        if not self.guest:
            self.guest = self.host.createGenericWindowsGuest()
            self.uninstallOnCleanup(self.guest)

        # Enable file and printer sharing on the guest.
        self.guest.xmlrpcExec("netsh firewall set service type=fileandprint "
                              "mode=enable profile=all")

        self.exports = []
        for i in range(self.SR_COUNT):
            # Create a user account.
            if self.SR_COUNT == 1:
                # Preserve old TC-6723 behaviour
                user = "Administrator"
                password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
            else:
                user = xenrt.randomGuestName()[0:10]
                password = "%s%u." % (self.passwordString(), i)
                self.guest.xmlrpcExec("net user %s %s /ADD" % (user, password))
            
            # Share a directory.
            sharedir = self.guest.xmlrpcTempDir()
            sharename = "XENRTSHARE%u" % (i)
            self.guest.xmlrpcExec("net share %s=%s /GRANT:%s,FULL" %
                                  (sharename, sharedir, user))
            if user != "Administrator":
                self.guest.xmlrpcExec("icacls %s /GRANT %s:F" %
                                      (sharedir, user))

            # Copy the PV tools ISO from the host to use as an example ISO
            # in our CIFS SR
            remotefile = self.host.toolsISOPath()
            if not remotefile:
                raise xenrt.XRTError("Could not find PV tools ISO in dom0")
            cd = "%s/TC6723.iso" % (xenrt.TEC().getWorkdir())
            sh = self.host.sftpClient()
            try:
                sh.copyFrom(remotefile, cd)
            finally:
                sh.close()
            self.guest.xmlrpcSendFile(cd, 
                                      "%s\\TC6723-%u.iso" % (sharedir, i),
                                      usehttp=True)
            if user != "Administrator":
                self.guest.xmlrpcExec("icacls %s\\TC6723-%u.iso /GRANT %s:F" %
                                      (sharedir, i, user))
            self.exports.append((sharename, user, password))

        self.client = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.client)

    def doCreate(self, index):
        # Attach the share as a CIFS ISO on the host.
        sharename, user, password = self.exports[index]
        sr = xenrt.lib.xenserver.CIFSISOStorageRepository(self.host,
                                                       "cifstest%u" % (index))
        self.srs.append(sr)
        self.srsToRemove.append(sr)
         
        sr.create(self.guest.getIP(),
                  sharename,
                  "iso",
                  "iso",
                  username=user,
                  password=password)

    def doUse(self, index):
        isoname = "TC6723-%u.iso" % (index)
        
        # Use the CD in the client VM
        time.sleep(30)
        self.client.changeCD(isoname)
        time.sleep(30)

        device = self.host.minimalList("vbd-list", 
                                       "device", 
                                       "type=CD vdi-name-label=%s vm-uuid=%s" %
                                       (isoname,
                                        self.client.getUUID()))[0]
        self.client.execguest("mount /dev/%s /mnt" % (device))
        try:
            self.client.execguest("test -e /mnt/Linux/install.sh")
        finally:
            self.client.execguest("umount /mnt")

        # Eject the CD
        self.host.getCLIInstance().execute("vm-cd-eject uuid=%s" %
                                           (self.client.getUUID()))

    def doRemove(self, index):
        # Remove the SR
        sr = self.srs[index]
        sr.remove()
        sharename, user, password = self.exports[index]
        if not self.host.execdom0("mount | grep %s" % (sharename),
                                  retval="code"):
            raise xenrt.XRTFailure("CIFS share appears to be mounted after "
                                   "removing SR.")
        self.srsToRemove.remove(sr)
        
    def run(self, arglist=None):

        for i in range(self.SR_COUNT):
            if self.runSubcase("doCreate", (i), "SRCreate", str(i)) != \
                   xenrt.RESULT_PASS:
                return
        for i in range(self.SR_COUNT):
            if self.runSubcase("doUse", (i), "UseSR", str(i)) != \
                   xenrt.RESULT_PASS:
                return
        for i in range(self.SR_COUNT):
            if self.runSubcase("doRemove", (i), "SRForget", str(i)) != \
                   xenrt.RESULT_PASS:
                return

    def postRun(self):
        try:
            self.host.getCLIInstance().execute("vm-cd-eject uuid=%s" %
                                               (self.client.getUUID()))
        except:
            pass
        for sr in self.srsToRemove:
            try:
                sr.remove()
            except:
                pass


class TC10860(TC6723):
    """Basic Secret functionality check """
    
    SR_COUNT = 2

    def passwordString(self):
        # The password string has to be wierd
        # we will be doing a grep for this string 
        # in all the logs.
        return 'kAnj1rapally'

    def prepare(self, arglist=None):
        TC6723.prepare(self)
        self.secrets = []

    def doCreateWithSecret(self, index):
        # Attach the share as a CIFS ISO on the host.
        sharename, user, password = self.exports[index]
        sr = xenrt.lib.xenserver.CIFSISOStorageRepository(self.host,
                                                       "cifstest%u" % (index))
        self.srs.append(sr)
        self.srsToRemove.append(sr)
        
        # We have to create a secret
        secret_uuid = self.host.createSecret(password)
        self.secrets.append(secret_uuid)
        
        sr.create(self.guest.getIP(),
                  sharename,
                  "iso",
                  "iso",
                  username=user,
                  password=secret_uuid,
                  use_secret=True)


    def doListWithSecret(self, index):

        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            # As a result of the fix for CA-113392, SR's secret is duplicated and 
            # a unique secret uuid is used for each pbd creation.
            # Hence, find the secret having the same value as that of sr
            secretList = self.host.getSecrets(self.exports[index][2])
            srSecret = self.secrets[index]
        
            # Find duplicate secret
            pbdSecret = ''.join([secret for secret in secretList if secret != srSecret])

            cli = self.host.getCLIInstance()
            uuids = cli.execute('pbd-list','device-config:cifspassword_secret=%s' 
                                            % pbdSecret, minimal=True)
            uuidsList = []
            uuidsList.append(uuids)
            uuids1 = set(uuidsList)
        else:
            uuids1 = set(self.host.minimalList('pbd-list',
                                                args='device-config:cifspassword_secret=%s' %
                                                self.secrets[index]))
        uuids2 = set(self.srs[index].getPBDs().keys())

        if len(uuids1) == len(uuids2): 
            if len(uuids1 - uuids2) != 0:
                raise xenrt.XRTFailure("Incorrect list of PBDs")
        else:
            raise xenrt.XRTFailure("Incorrect list of PBDs")
    
    
    def doPlugAndUnplug(self, index):
        cli = self.host.getCLIInstance()
        uuids = self.srs[index].getPBDs()
        
        for pbd in uuids.keys():
            cli.execute("pbd-unplug uuid=%s" % pbd)
        
        for pbd in uuids.keys():
            cli.execute("pbd-plug uuid=%s" % pbd)

    def doGrepForPassword(self, index):
        tarfile = self.host.getBugTool()
        sharename, user, password = self.exports[index]
        
        rot13_passwd = xenrt.rot13Encode(password)
        out = xenrt.command("tar -O -xf %s | grep -e '%s' -e '%s' | wc -l" 
                            % (tarfile, password, rot13_passwd))
        
        times = int(out.strip())
        if times != 0:
            raise xenrt.XRTFailure('Clear text password(%s) occured %u times' % 
                                   (password, times))
        
    def run(self, arglist=None):
        
        if self.runSubcase("doCreateWithSecret", 0, "SRCreateWithSecret", "0") != \
                xenrt.RESULT_PASS:
            return
        
        if self.runSubcase("doUse", 0, "UseSR", "0") != \
                xenrt.RESULT_PASS:
            return
        
        if self.runSubcase("doListWithSecret", 0, "ListSRWithSecret", "0") != \
                xenrt.RESULT_PASS:
            return
        
        if self.runSubcase("doPlugAndUnplug", 0, "PlugAndUnplugSRWithSecret", "0") != \
                xenrt.RESULT_PASS:
            return
        
        if self.runSubcase("doRemove", 0, "SRForget", "0") != \
                xenrt.RESULT_PASS:
            return

        if self.runSubcase("doGrepForPassword", 0, "GrepPasswordInLogs", "0") != \
                xenrt.RESULT_PASS:
            return

    def postRun(self):
        TC6723.postRun(self)
        for uuid in self.secrets:
            self.host.deleteSecret(uuid)
            

class TC10615(TC6723):
    """Operation of two CIFS ISO SRs using different credentials"""

    SR_COUNT = 2

class _VDICopy(xenrt.TestCase):
    """Base class for testcases that verify vdi-copy works between different SR types"""

    FROM_TYPE = None
    TO_TYPE = None
    SAME_HOSTS = True
    HOST_TYPE = None
    FIND_SR_BY_NAME = False
    VDI_SIZE = 100 * xenrt.MEGA
    FORCE_FILL_VDI = False

    def prepare(self, arglist):

        if self.SAME_HOSTS:
            # Get the host
            self.srcHost = self.getDefaultHost()
            self.destHost = self.srcHost

        else :
            # Get the pool
            newPool = self.getDefaultPool()

            # Check we have 2 hosts
            if len(newPool.getHosts()) < 3:
                raise xenrt.XRTError("Pool must have atleast 3 hosts")

            if self.HOST_TYPE == "slavetoslave":
                if len(newPool.getSlaves()) < 2:
                    raise xenrt.XRTError("Pool must have 2 slave hosts")
                self.srcHost =  self.getHost("RESOURCE_HOST_1")
                self.destHost =  self.getHost("RESOURCE_HOST_2")
            elif self.HOST_TYPE == "slavetomaster":
                self.srcHost = self.getHost("RESOURCE_HOST_1") 
                self.destHost = newPool.master
            else :
                self.srcHost = newPool.master
                self.destHost =   self.getHost("RESOURCE_HOST_1")

        cli = self.srcHost.getCLIInstance()
        self.cli = cli

        # Get the two SRs
        if self.FIND_SR_BY_NAME:
            fromSRs = self.srcHost.getSRByName(self.FROM_TYPE)
        else:
            fromSRs = self.srcHost.getSRs(type=self.FROM_TYPE)
       
        if len(fromSRs) == 0:
            raise xenrt.XRTError("Could not find %s SR on the host" %
                                 (self.FROM_TYPE))
        self.fromSR = fromSRs[0]
        
        if self.FIND_SR_BY_NAME:
            toSRs = self.destHost.getSRByName(self.TO_TYPE)
        else:
            toSRs = self.destHost.getSRs(type=self.TO_TYPE)
            
        if len(toSRs) == 0:
            raise xenrt.XRTError("Could not find %s SR on the host" %
                                 (self.TO_TYPE))
        self.toSR = toSRs[0]
        self.copies = {}
        self.vdisToDestroy = []

        # Create a VDI on the fromSR
        args = []
        args.append("sr-uuid=%s" % (self.fromSR))
        args.append("name-label=\"XenRT Test %s-%s\"" %
                    (self.FROM_TYPE, self.TO_TYPE))
        args.append("type=user")
        args.append("virtual-size=%d" % (self.VDI_SIZE))
        self.vdi = cli.execute("vdi-create", string.join(args)).strip()
        self.vdisToDestroy.append(self.vdi)
        self.copies["original"] = self.vdi
        self.vdi_size = int(self.srcHost.genParamGet("vdi", self.vdi, "virtual-size"))
        self.vdi_size_unit = \
            (self.vdi_size % xenrt.GIGA == 0) and xenrt.GIGA \
            or (self.vdi_size % xenrt.MEGA == 0) and xenrt.MEGA \
            or (self.vdi_size % xenrt.KILO == 0) and xenrt.KILO \
            or 1
        self.vdi_size_in_unit = self.vdi_size / self.vdi_size_unit
        
        # Put a filesystem on it
        self.srcHost.execdom0("echo '/sbin/mkfs.ext3 /dev/${DEVICE}' > "
                           "/tmp/mkfs.sh")
        self.srcHost.execdom0("chmod u+x /tmp/mkfs.sh")
        self.srcHost.execdom0("/opt/xensource/debug/with-vdi %s /tmp/mkfs.sh" %
                           (self.vdi))

        # Writing data into it; This is required on thin-lvhd as it always return true and
        # only be empty in next step due to initial allocation size.
        if self.FORCE_FILL_VDI:
            cmd = "%s/remote/patterns.py /dev/\\${DEVICE} %d write 3" % \
                (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.vdi_size)
            self.srcHost.execdom0("echo '%s' > /tmp/dd.sh" % cmd)
            self.srcHost.execdom0("chmod u+x /tmp/dd.sh")
            self.srcHost.execdom0("/opt/xensource/debug/with-vdi %s /tmp/dd.sh" % (self.vdi), timeout=900)

        # Checksum the entire VDI
        script = 'if [ -z "$1" ]; then md5sum "/dev/${DEVICE}"; else dd if="/dev/${DEVICE}" bs="$1" count="$2" 2>/dev/null | md5sum; fi'
        self.srcHost.execdom0("echo '%s' > /tmp/md5.sh" % script)
        self.srcHost.execdom0("chmod u+x /tmp/md5.sh")

        if not self.SAME_HOSTS:
            self.destHost.execdom0("echo '%s' > /tmp/md5.sh" % script)
            self.destHost.execdom0("chmod u+x /tmp/md5.sh") 

        self.md5sum = self.srcHost.execdom0(\
            "/opt/xensource/debug/with-vdi %s /tmp/md5.sh" %
            (self.vdi)).splitlines()[-1].split()[0]
        if "The device is not currently attached" in self.md5sum:
            raise xenrt.XRTError("Device not attached when trying to md5sum")

    def doCopy(self, sourcetag, targetsruuid, targettag):
        vdiuuid = self.copies[sourcetag]
        xenrt.TEC().logverbose("Attempting to copy to SR %s" % (targetsruuid))
        args = []
        args.append("uuid=%s" % (vdiuuid))
        args.append("sr-uuid=%s" % (targetsruuid))
        newVDI = self.cli.execute("vdi-copy", string.join(args)).strip()
        self.vdisToDestroy.append(newVDI)
        self.copies[targettag] = newVDI

    def doCheck(self, tag):
        vdi_uuid = self.copies[tag]

        command = "/opt/xensource/debug/with-vdi %s /tmp/md5.sh" % vdi_uuid
        host = (tag == "other") and self.destHost or self.srcHost

        if self.FROM_TYPE == "cslg" or self.TO_TYPE == "cslg":
            vdi_size = int(host.genParamGet("vdi", vdi_uuid, "virtual-size"))
            if vdi_size != self.vdi_size:
                if not (0 < vdi_size - self.vdi_size <= 8 * xenrt.MEGA):
                    errorMessage = "Size differences between the original and the new VDI is wrong: original (%d) v.s. new (%d)" % (self.vdi_size, vdi_size)
                    if isinstance(host, xenrt.lib.xenserver.MNRHost) and host.productVersion == 'Oxford': # this issue is seen only in Oxford
                        xenrt.TEC().warning(errorMessage)
                    else:
                        raise xenrt.XRTFailure(errorMessage)
                command += " %s %s" % (self.vdi_size_unit, self.vdi_size_in_unit)

        md5sum = host.execdom0(command).splitlines()[-1].split()[0]

        if "The device is not currently attached" in md5sum:
            raise xenrt.XRTError("Device not attached when trying to md5sum")
        if md5sum != self.md5sum:
            raise xenrt.XRTFailure("Copy and original VDIs have different "
                                   "checksums")
        
        # Check the physical utilisation is appropriate taking into
        # account that LVM is fully provisioned for non-snapshot VDIs
        sr_uuid = self.destHost.genParamGet("vdi", vdi_uuid, "sr-uuid")
        sr_type = self.destHost.genParamGet("sr", sr_uuid, "type")
        # TODO
        
    def run(self, arglist):
        # Attempt to copy the VDI onto the same SR type
        xenrt.TEC().logverbose("Attempting to copy within the %s SR" %
                               (self.FROM_TYPE))
        if self.runSubcase("doCopy",
                           ("original", self.fromSR, "intra"),
                           "Copy",
                           "SameSR") == \
                           xenrt.RESULT_PASS:
            self.runSubcase("doCheck", ("intra"), "Check", "SameSR")
        
        # Now onto the other
        xenrt.TEC().logverbose("Attempting to copy to the %s SR" %
                               (self.TO_TYPE))
        if self.runSubcase("doCopy",
                           ("original", self.toSR, "other"),
                           "Copy",
                           "OtherSR") == \
                           xenrt.RESULT_PASS:
            if self.runSubcase("doCheck", ("other"), "Check", "OtherSR") == \
                   xenrt.RESULT_PASS:

                # Now back again
                xenrt.TEC().logverbose("Attempting a final copy to the %s SR" %
                                       (self.FROM_TYPE))
                if self.runSubcase("doCopy",
                                   ("other", self.fromSR, "back"),
                                   "Copy",
                                   "OriginalSR") == \
                                   xenrt.RESULT_PASS:
                    self.runSubcase("doCheck", ("back"), "Check", "OriginalSR")

    def postRun(self):

        # destroying target vdis created during vdicopy.
        for vdi in self.vdisToDestroy:
            try:
                self.cli.execute("vdi-destroy","uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception attempting to destroy VDI %s" %
                                    (vdi))

class TC8458(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR and an ext SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "ext"

class TC20941(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR and a file SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "file"

class TC20942(_VDICopy):
    """Verify vdi-copy between an nfs SR and a file SR"""
    FROM_TYPE = "file"
    TO_TYPE = "nfs"

class TC20943(_VDICopy):
    """Verify vdi-copy between an ext SR and a file SR"""
    FROM_TYPE = "ext"
    TO_TYPE = "file"


class TC8459(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR and an nfs SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "nfs"

class TC8460(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR and a netapp SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "netapp"

class TC8461(_VDICopy):
    """Verify vdi-copy between an ext SR and an nfs SR"""
    FROM_TYPE = "ext"
    TO_TYPE = "nfs"

class TC8462(_VDICopy):
    """Verify vdi-copy between an ext SR and a netapp SR"""
    FROM_TYPE = "ext"
    TO_TYPE = "netapp"

class TC8463(_VDICopy):
    """Verify vdi-copy between an nfs SR and a netapp SR"""
    FROM_TYPE = "nfs"
    TO_TYPE = "netapp"

class TC9930(_VDICopy):
    """Verify vdi-copy between an LVM SR and CVSM FC SR"""
    FROM_TYPE = "lvm"
    TO_TYPE = "cslg"

class TC9415(_VDICopy):
    """Verify vdi-copy between an LVM SR and CVSM iSCSI SR"""
    FROM_TYPE = "lvm"
    TO_TYPE = "cslg"

class TC27155(_VDICopy):
    """Verify vdi-copy between an a NFS SR with no sub directory and lvmoiscsi SR"""
    FROM_TYPE = "nfs"
    TO_TYPE = "lvmoiscsi"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA

class TC27156(_VDICopy):
    """Verify vdi-copy between an ext SR and a lvmoiscsi SR"""
    FROM_TYPE = "ext"
    TO_TYPE = "lvmoiscsi"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA

class TC20953(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR and a NFS SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "nfs"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA

class TC27219(_VDICopy):
    """Verify vdi-copy between an a NFS SR on master and lvmoiscsi SR on slave"""
    FROM_TYPE = "nfs"
    TO_TYPE = "lvmoiscsi"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA
    HOST_TYPE = "mastertoslave"
    SAME_HOSTS  = False

class TC27217(_VDICopy):
    """Verify vdi-copy between an ext SR on master and a lvmoiscsi SR on slave"""
    FROM_TYPE = "ext"
    TO_TYPE = "lvmoiscsi"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA
    HOST_TYPE = "mastertoslave"
    SAME_HOSTS  = False

class TC27221(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR on master and a NFS SR on slave"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "nfs"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA
    HOST_TYPE = "mastertoslave"
    SAME_HOSTS  = False

class TC27220(_VDICopy):
    """Verify vdi-copy between an a NFS SR on slave and lvmoiscsi SR on slave"""
    FROM_TYPE = "nfs"
    TO_TYPE = "lvmoiscsi"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA
    HOST_TYPE = "slavetoslave"
    SAME_HOSTS  = False

class TC27218(_VDICopy):
    """Verify vdi-copy between an ext SR on lsave and a lvmoiscsi SR on slave"""
    FROM_TYPE = "ext"
    TO_TYPE = "lvmoiscsi"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA
    HOST_TYPE = "slavetoslave"
    SAME_HOSTS  = False

class TC27222(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR on slave and a NFS SR on slave"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "nfs"
    FORCE_FILL_VDI = True
    VDI_SIZE = 20 * xenrt.GIGA
    HOST_TYPE = "slavetoslave"
    SAME_HOSTS  = False

class TC20954(_VDICopy):
    """Verify vdi-copy between an ext SR and a NFS SR with no sub directory"""
    FROM_TYPE = "ext"
    TO_TYPE = "nfs"

class TC20955(_VDICopy):
    """Verify vdi-copy between an NFS SR with no sub directory and a netapp SR"""            
    FROM_TYPE = "nfs"
    TO_TYPE = "netapp"

# NFS SR with no sub directory tests and file SR
class TC20956(_VDICopy):
    """Verify vdi-copy between an NFS SR with no sub directory and a file SR"""
    FIND_SR_BY_NAME = True
    FROM_TYPE = "nfssr_nosubdir" # options="nosubdir"
    TO_TYPE   = "nfssr_filesr" # options="filesr" 

class TC20957(_VDICopy):
    """Verify vdi-copy between an NFS SR and a NFS SR with no sub directory"""
    FIND_SR_BY_NAME = True
    FROM_TYPE = "nfssr_classic" # classic nfssr
    TO_TYPE   = "nfssr_nosubdir" # options="nosubdir" 

class TC26951(_VDICopy):
    """Verify vdi-copy between CIFS SR and NFS SR v3."""
    FIND_SR_BY_NAME = True
    FROM_TYPE = "cifssr"
    TO_TYPE = "nfssr_v3"

class TC26952(_VDICopy):
    """Verify vdi-copy between CIFS SR and NFS SR v4."""
    FIND_SR_BY_NAME = True
    FROM_TYPE = "cifssr"
    TO_TYPE = "nfssr_v4"

class TC26953(_VDICopy):
    """Verify vdi-copy between CIFS SR and NFS FILE SR."""
    FIND_SR_BY_NAME = True
    FROM_TYPE = "cifssr"
    TO_TYPE = "nfssr_filesr"

class TC26954(_VDICopy):
    """Verify vdi-copy between CIFS SR and NFS SR with no sub directory."""
    FIND_SR_BY_NAME = True
    FROM_TYPE = "cifssr"
    TO_TYPE = "nfssr_nosubdir"

class TC27108(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR and a local smapiv3 SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "btrfs"

class TC27109(_VDICopy):
    """Verify vdi-copy between an nfs SR and a local smapiv3 SR"""
    FROM_TYPE = "nfs"
    TO_TYPE = "btrfs"

class TC27110(_VDICopy):
    """Verify vdi-copy between a local smapiv3 SR and a lvmoiscsi SR"""
    FROM_TYPE = "btrfs"
    TO_TYPE = "lvmoiscsi"

class TC27111(_VDICopy):
    """Verify vdi-copy between a local smapiv3 SR and a nfs SR"""
    FROM_TYPE = "btrfs"
    TO_TYPE = "nfs"

class TC27177(_VDICopy):
    """Verify vdi-copy between an lvmoiscsi SR and a local smapiv3 SR"""
    FROM_TYPE = "lvmoiscsi"
    TO_TYPE = "rawnfs"

class TC27178(_VDICopy):
    """Verify vdi-copy between an nfs SR and a local smapiv3 SR"""
    FROM_TYPE = "nfs"
    TO_TYPE = "rawnfs"

class TC27179(_VDICopy):
    """Verify vdi-copy between a local smapiv3 SR and a lvmoiscsi SR"""
    FROM_TYPE = "rawnfs"
    TO_TYPE = "lvmoiscsi"

class TC27180(_VDICopy):
    """Verify vdi-copy between a local smapiv3 SR and a nfs SR"""
    FROM_TYPE = "rawnfs"
    TO_TYPE = "nfs"


#############################################################################
# VDI resize testcases

class _TCResize(xenrt.TestCase):

    SRTYPE = "lvm"
    INITIAL_SIZE = None
    ONLINE = False
    DOM0 = False
    SMCONFIG = None
    
    def prepare(self, arglist):
        self.vdi = None
        self.vbd = None
        self.guest = None
        self.host = self.getDefaultHost()
        if self.host.pool:
            self.host = self.host.pool.master
        if self.DOM0 == "slave":
            self.attachhost = self.host.pool.getSlaves()[0]
        else:
            self.attachhost = self.host
        self.cli = self.host.getCLIInstance()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]
        if self.INITIAL_SIZE:
            self.vdi = self.host.createVDI(self.INITIAL_SIZE,
                                           sruuid=self.sr,
                                           smconfig=self.SMCONFIG)
            s = self.host.genParamGet("vdi", self.vdi, "virtual-size")
            
            # In a LUN based VDIs,The virtual machine storage operations are mapped directly onto the array APIs using a LUN per VDI representation.
            # There will be always an extra space needed in the volume for the LUN that is reserved.
            # This is due to the geometry of the LUN making it slightly larger than the requested size.
            # Hence the obtained VDI size is always greater than the requested VDI size in a LUN based VDI scenario.

            if str(self.INITIAL_SIZE) != s:
            #    raise xenrt.XRTError("VDI virtual-size is not as expected",
            #                         "Wanted %u, got %s" %
            #                         (self.INITIAL_SIZE, s))
                xenrt.TEC().logverbose("VDI virtual-size is not as expected",
                                     "Wanted %u, got %s" %
                                     (self.INITIAL_SIZE, s))
                xenrt.TEC().logverbose("The obtained VDI size is always greater than the requested VDI size")
            
        if self.ONLINE:
            self.guest = self.host.createGenericLinuxGuest()        
            self.uninstallOnCleanup(self.guest)
            args = []
            args.append("vdi-uuid=%s" % (self.vdi))
            args.append("vm-uuid=%s" % (self.guest.getUUID()))
            args.append("type=Disk")
            args.append("device=4")
            self.vbd = self.cli.execute("vbd-create",
                                        string.join(args)).strip()
            self.cli.execute("vbd-plug", "uuid=%s" % (self.vbd))

        if self.DOM0:
            args = []
            args.append("vdi-uuid=%s" % (self.vdi))
            args.append("vm-uuid=%s" % (self.attachhost.getMyDomain0UUID()))
            args.append("type=Disk")
            args.append("device=4")
            self.vbd = self.cli.execute("vbd-create",
                                        string.join(args)).strip()
            self.cli.execute("vbd-plug", "uuid=%s" % (self.vbd))

    def doResize(self, newbytes, online, experror):
        if isinstance(experror, basestring):
            experror = [experror]
        args = ["uuid=%s" % (self.vdi)]
        if online != None:
            if online:
                args.append("online=true")
            else:
                args.append("online=false")
        args.append("disk-size=%u" % (newbytes))
        try:
            self.cli.execute("vdi-resize", string.join(args))
        except xenrt.XRTFailure, e:
            # Were we expecting an error
            if experror:
                for err in experror:
                    if re.search(err, e.data):
                        # This is what we expected
                        xenrt.TEC().logverbose("CLI error as expected")
                        return
                xenrt.TEC().logverbose("CLI error not as expected")
                raise e
            # No error expected but we got one
            raise e
        # Did we get a success when we expected an error?
        if experror:
            raise xenrt.XRTFailure("CLI command succeeded when an error was "
                                   "expected")
        s = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        if long(newbytes) > s:
            raise xenrt.XRTFailure("VDI virtual-size is not as expected",
                                   "Wanted %u, got %u" % (newbytes, s))
        # If this is an online resize check the VM can see and use the extra
        # space
        if self.ONLINE:
            # Allow time for the VM to spot the size increase
            time.sleep(30)
            # Check the size
            gs = long(self.guest.execguest("cat /sys/block/xvde/size")) * 512
            if gs != s:
                raise xenrt.XRTFailure("VM's disk size does not match the "
                                       "new VDI size",
                                       "VDI %u, VM %u" % (s, gs))
            # Perform a read and a write
            c = chr(ord('a') + random.randint(0, 25))
            self.guest.execguest("echo -n %s > /tmp/char" % (c))
            self.guest.execguest("dd if=/tmp/char of=/dev/xvde bs=1 seek=%u" %
                                 (gs - 1))
            self.guest.execguest("sync")
            data = self.guest.execguest("dd if=/dev/xvde bs=1 seek=%u" %
                                        (gs - 1)).strip()
            if data != c:
                raise xenrt.XRTFailure("Data write/read inconsistent")

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

    def vdicommand(self, command):
        sftp = self.host.sftpClient()
        sd = self.host.hostTempDir()
        t = xenrt.TempDirectory()
        
        s = "%s/cmd.sh" % (sd)
        filename = "%s/cmd.sh" % (t.path())
        
        file(filename, "w").write(command)
        sftp.copyTo("%s/cmd.sh" % (t.path()), s)
        self.host.execdom0("chmod +x %s" % (s))
        data = self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" %  
                                  (self.vdi, s))
        self.host.execdom0("rm -rf %s" % (sd))
        t.remove()
        return data

class _TCResizeShrink(_TCResize):

    INITIAL_SIZE = 8589934592
    SHRINK_SIZE_1 = 4294967296

    def run(self, arglist):
        if self.runSubcase("doResize",
                           (self.SHRINK_SIZE_1, None, ["VDI Invalid size", "Shrinking is not supported"]),
                           "Shrink",
                           "nGiB") != \
               xenrt.RESULT_PASS:
            return    
        if self.runSubcase("doResize",
                           (self.INITIAL_SIZE - 1, None, ["VDI Invalid size", "Shrinking is not supported"]),
                           "Shrink",
                           "1B") != \
               xenrt.RESULT_PASS:
            return

class _TCResizeGrow(_TCResize):

    INITIAL_SIZE = 8589934592

    def run(self, arglist):
        s = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        if long(self.INITIAL_SIZE) < s:
            self.INITIAL_SIZE = s
        if self.runSubcase("doResize",
                           (self.INITIAL_SIZE + 1, None, None),
                           "Grow",
                           "1B") != \
               xenrt.RESULT_PASS:
            return

class _TCResizeGrow2(_TCResize):

    INITIAL_SIZE = 8589934592
    STEP = 4294967296

    def run(self, arglist):
        if self.runSubcase("doResize",
                           (self.INITIAL_SIZE + self.STEP, None, None),
                           "Grow",
                           "Once") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("doResize",
                           (self.INITIAL_SIZE + self.STEP + self.STEP, None, None),
                           "Grow",
                           "Twice") != \
               xenrt.RESULT_PASS:
            return

class _TCResizeOnline(_TCResize):

    INITIAL_SIZE = 8589934592
    STEP = 4294967296
    ONLINE = True

    def run(self, arglist):
        if self.runSubcase("doResize",
                           (self.INITIAL_SIZE + self.STEP, False, "VDI_IN_USE"),
                           "Neg",
                           "NoOnline") != \
               xenrt.RESULT_PASS:
            return
        if self.runSubcase("doResize",
                           (self.INITIAL_SIZE + self.STEP, True, None),
                           "Grow",
                           "Online") != \
               xenrt.RESULT_PASS:
            return

class _TCResizeDataCheck(_TCResize):

    INITIAL_SIZE = 4294967296
    STEP = 4294967296
    DOM0 = True
    FORCEOFFLINE = False

    def writePattern(self, length):
        self.attachhost.execdom0("%s/remote/patterns.py /dev/xvde %d write 1" %
                                 (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), length))
        self.checkPattern(length)

    def checkPattern(self, length):
        try:
            self.attachhost.execdom0("%s/remote/patterns.py /dev/xvde %d read 1" %
                                     (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), length))
        except xenrt.XRTFailure, e:
            if re.search("Inconsistency", e.data):
                e.changeReason("Data check inconsistency")
            raise e

    def prepare(self, arglist):
        _TCResize.prepare(self, arglist)
        
        # Attach the VDI and write a pattern to it
        s = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        self.writePattern(s)

        # Detach the VDI from dom0
        self.cli.execute("vbd-unplug", "uuid=%s" % (self.vbd))

    def run(self, arglist):
        s = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        
        # Resize the VDI to 8GB
        if self.runSubcase("doResize",
                           (self.INITIAL_SIZE + self.STEP, None, None),
                           "Grow",
                           "Offline") != \
               xenrt.RESULT_PASS:
            return
        
        # Attach the VDI to dom0 and validate the pattern on the first 4GB
        self.cli.execute("vbd-plug", "uuid=%s" % (self.vbd))
        if self.runSubcase("checkPattern", (s), "Check", "4GB") \
               != xenrt.RESULT_PASS:
            return
        
        # Write a pattern to the 8GB VDI
        s = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        if self.runSubcase("writePattern", (s), "Write", "8GB") \
               != xenrt.RESULT_PASS:
            return
        
        # Perform an online (if supported) resize of the VDI to 12GB
        if self.FORCEOFFLINE:
            self.cli.execute("vbd-unplug", "uuid=%s" % (self.vbd))
            if self.runSubcase("doResize",
                               (self.INITIAL_SIZE + self.STEP + self.STEP,
                                None,
                                None),
                               "Grow",
                               "Again") != \
                               xenrt.RESULT_PASS:
                return
        else:
            if self.runSubcase("doResize",
                               (self.INITIAL_SIZE + self.STEP + self.STEP,
                                True,
                                None),
                               "Grow",
                               "Online") != \
                               xenrt.RESULT_PASS:
                return
            self.cli.execute("vbd-unplug", "uuid=%s" % (self.vbd))
        
        # Reattach the VDI
        self.cli.execute("vbd-plug", "uuid=%s" % (self.vbd))

        # Validate the patterns on the first and second 4GB chunks
        if self.runSubcase("checkPattern", (s), "Check", "8GB") \
               != xenrt.RESULT_PASS:
            return

# LVM resize
class TC8475(_TCResizeShrink):
    """Attempting to shrink a LVM VDI should fail with a suitable error."""

    SRTYPE = "lvm"

class TC27158(_TCResizeShrink):
    """Attempting to shrink a LVM VDI should fail with a suitable error."""

    SRTYPE = "lvmoiscsi"

class TC8476(_TCResizeGrow):
    """Grow a LVM VDI of a round size by 1 byte."""

    SRTYPE = "lvm"

class TC8477(_TCResizeGrow2):
    """Grow a LVM VDI twice in large chunks."""

    SRTYPE = "lvm"

class TC27159(_TCResizeGrow2):
    """Grow a LVM VDI twice in large chunks."""

    SRTYPE = "lvmoiscsi"

class TC8478(_TCResizeOnline):
    """Resize a LVM VDI attached to a running VM."""

    SRTYPE = "lvm"
    
class TC8479(_TCResizeDataCheck):
    """Data integrity of resized LVM VDI."""

    SRTYPE = "lvm"
    FORCEOFFLINE = True

class TC27160(_TCResizeDataCheck):
    """Data integrity of resized LVM VDI."""

    SRTYPE = "lvmoiscsi"
    FORCEOFFLINE = True

class TC8481(_TCResizeDataCheck):
    """Data integrity of resized LVM raw VDI."""

    SRTYPE = "lvm"
    SMCONFIG = "type=raw"
    FORCEOFFLINE = True
    
class TC8482(_TCResizeGrow2):
    """Grow a LVM raw VDI twice in large chunks."""

    SRTYPE = "lvm"
    SMCONFIG = "type=raw"

# EXT resize
class TC8485(_TCResizeShrink):
    """Attempting to shrink a VHDoEXT VDI should fail with a suitable error."""

    SRTYPE = "ext"
    
class TC8486(_TCResizeGrow):
    """Grow a VHDoEXT VDI of a round size by 1 byte."""

    SRTYPE = "ext"
    
class TC8487(_TCResizeGrow2):
    """Grow a VHDoEXT VDI twice in large chunks."""

    SRTYPE = "ext"

class TC8488(_TCResizeOnline):
    """Resize a VHDoEXT VDI attached to a running VM."""

    SRTYPE = "ext"

class TC8489(_TCResizeDataCheck):
    """Data integrity of resized VHDoEXT VDI."""

    SRTYPE = "ext"
    FORCEOFFLINE = True

# BTRFS resize
class TC27089(_TCResizeShrink):
    """Attempting to shrink a VHDoEXT VDI should fail with a suitable error."""

    SRTYPE = "btrfs"

class TC27090(_TCResizeGrow):
    """Grow a VHDoEXT VDI of a round size by 1 byte."""

    SRTYPE = "btrfs"
    
class TC27091(_TCResizeGrow2):
    """Grow a VHDoEXT VDI twice in large chunks."""

    SRTYPE = "btrfs"

class TC27092(_TCResizeDataCheck):
    """Data integrity of resized VHDoEXT VDI."""

    SRTYPE = "btrfs"
    FORCEOFFLINE = True


# RAWNFS resize
class TC27181(_TCResizeShrink):
    """Attempting to shrink a VHDoEXT VDI should fail with a suitable error."""

    SRTYPE = "rawnfs"

class TC27182(_TCResizeGrow):
    """Grow a VHDoEXT VDI of a round size by 1 byte."""

    SRTYPE = "rawnfs"
    
class TC27183(_TCResizeGrow2):
    """Grow a VHDoEXT VDI twice in large chunks."""

    SRTYPE = "rawnfs"

class TC27184(_TCResizeDataCheck):
    """Data integrity of resized VHDoEXT VDI."""

    SRTYPE = "rawnfs"
    FORCEOFFLINE = True


# NetApp resize
class TC8491(_TCResizeShrink):
    """Attempting to shrink a NetApp VDI should fail with a suitable error."""

    SRTYPE = "netapp"
 
class TC8492(_TCResizeGrow):
    """Grow a NetApp VDI of a round size by 1 byte."""

    SRTYPE = "netapp"
    
class TC8493(_TCResizeGrow2):
    """Grow a NetApp VDI twice in large chunks."""

    SRTYPE = "netapp"

class TC8494(_TCResizeOnline):
    """Resize a NetApp VDI attached to a running VM."""

    SRTYPE = "netapp"

class TC8495(_TCResizeDataCheck):
    """Data integrity of resized NetApp VDI."""

    SRTYPE = "netapp"
    FORCEOFFLINE = True

# CSLG iSCSI resize
class TC9411(_TCResizeShrink):
    """Attempting to shrink a CVSM VDI should fail with a suitable error."""

    SRTYPE = "cslg"

class TC9412(_TCResizeGrow):
    """Grow a CVSM VDI of a round size by 1 byte."""

    SRTYPE = "cslg"

class TC9413(_TCResizeOnline):
    """Resize a CVSM VDI attached to a running VM."""

    SRTYPE = "cslg"
    
class TC9418(_TCResizeGrow2):
    """Grow a CVSM VDI twice in large chunks."""

    SRTYPE = "cslg"
    
class TC9414(_TCResizeDataCheck):
    """Data integrity of resized CVSM VDI."""

    SRTYPE = "cslg"
    FORCEOFFLINE = True 

# CSLG FC
class TC9933(_TCResizeShrink):
    """Attempting to shrink a CVSM-FC VDI should fail with a suitable error."""

    SRTYPE = "cslg"

class TC9932(_TCResizeGrow):
    """Grow a CVSM-FC VDI of a round size by 1 byte."""

    SRTYPE = "cslg"

class TC9940(_TCResizeOnline):
    """Resize a CVSM FC VDI attached to a running VM."""

    SRTYPE = "cslg"

class TC9934(_TCResizeGrow2):
    """Grow a CVSM-fc VDI twice in large chunks."""

    SRTYPE = "cslg"
    
class TC9935(_TCResizeDataCheck):
    """Data integrity of resized CVSM-FC VDI."""

    SRTYPE = "cslg"
    FORCEOFFLINE = True  

# Equallogic resize
class TC8497(_TCResizeShrink):
    """Attempting to shrink a Equallogic VDI should fail with a suitable error."""

    SRTYPE = "equal"
    INITIAL_SIZE = 32212254720
    SHRINK_SIZE_1 = 16106127360

class TC8498(_TCResizeGrow):
    """Grow a Equallogic VDI of a round size by 1 byte."""

    SRTYPE = "equal"
    INITIAL_SIZE = 16106127360
    
class TC8499(_TCResizeGrow2):
    """Grow a Equallogic VDI twice in large chunks."""

    SRTYPE = "equal"
    INITIAL_SIZE = 16106127360
    STEP = 16106127360

class TC8500(_TCResizeOnline):
    """Resize a Equallogic VDI attached to a running VM."""

    SRTYPE = "equal"
    INITIAL_SIZE = 16106127360
    STEP = 16106127360

class TC8501(_TCResizeDataCheck):
    """Data integrity of resized Equallogic VDI."""

    SRTYPE = "equal"
    FORCEOFFLINE = True
    INITIAL_SIZE = 16106127360
    STEP = 16106127360

# NFS resize
class TC8503(_TCResizeShrink):
    """Attempting to shrink a NFS VDI should fail with a suitable error."""

    SRTYPE = "nfs"

class TC20931(_TCResizeShrink):
    """Attempting to shrink a NFS VDI should fail with a suitable error."""

    SRTYPE = "file"


class TC8504(_TCResizeGrow):
    """Grow a NFS VDI of a round size by 1 byte."""

    SRTYPE = "nfs"

class TC20932(_TCResizeGrow):
    """Grow a filesr VDI of a round size by 1 byte."""

    SRTYPE = "file"

class TC8505(_TCResizeGrow2):
    """Grow a NFS VDI twice in large chunks."""

    SRTYPE = "nfs"

class TC20933(_TCResizeGrow2):
    """Grow a filesr VDI twice in large chunks."""

    SRTYPE = "file"


class TC8506(_TCResizeOnline):
    """Resize a NFS VDI attached to a running VM."""

    SRTYPE = "nfs"

class TC8507(_TCResizeDataCheck):
    """Data integrity of resized NFS VDI."""

    SRTYPE = "nfs"
    FORCEOFFLINE = True

class TC20934(_TCResizeDataCheck):
    """Data integrity of resized NFS VDI."""

    SRTYPE = "file"
    FORCEOFFLINE = True


class TC8509(_TCResizeDataCheck):
    """Data integrity of resized LVMoISCSI VDI using slave dom0 block attach"""

    SRTYPE = "lvmoiscsi"
    DOM0 = "slave"
    FORCEOFFLINE = True

# CIFS Resize
class TCCIFSVDIResizeShrink(_TCResizeShrink):
    """Attempting to shrink a CIFS VDI should fail with a suitable error."""

    SRTYPE = "cifs"

class TCCIFSVDIResizeGrowSmall(_TCResizeGrow):
    """Grow a CIFS VDI of a round size by 1 byte."""

    SRTYPE = "cifs"

class TCCIFSVDIResizeGrowLarge(_TCResizeGrow2):
    """Grow a CIFS VDI twice in large chunks."""

    SRTYPE = "cifs"

class TCCIFSVDIResizeDataCheck(_TCResizeDataCheck):
    """Data integrity of resized CIFS VDI."""

    SRTYPE = "cifs"
    FORCEOFFLINE = True

class TCFCOEVDIResizeGrowSmall(_TCResizeGrow):
    """Grow a FCoE VDI of a round size by 1 byte."""

    SRTYPE = "lvmofcoe"

class TCFCOEVDIResizeGrowLarge(_TCResizeGrow2):
    """Grow a FCoE VDI twice in large chunks."""

    SRTYPE = "lvmofcoe"

class TCFCOEVDIResizeDataCheck(_TCResizeDataCheck):
    """Data integrity of resized FCoE VDI."""

    SRTYPE = "lvmofcoe"
    FORCEOFFLINE = True
    
#############################################################################
# VDI create testcases

class _TCVDICreate(xenrt.TestCase):

    SRTYPE = "lvm"
    INITIAL_SIZE = None
    SMCONFIG = None
    ROUNDUPALLOWED = True
    
    def prepare(self, arglist):
        self.vdi = None
        self.vbd = None
        self.guest = None
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]

    def doCreate(self):
        self.vdi = self.host.createVDI(self.INITIAL_SIZE,
                                       sruuid=self.sr,
                                       smconfig=self.SMCONFIG)

    def checkSize(self):
        s = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        if (self.ROUNDUPALLOWED and s < self.INITIAL_SIZE) or \
               (not self.ROUNDUPALLOWED and s != self.INITIAL_SIZE):
            raise xenrt.XRTFailure("VDI virtual-size is not as expected",
                                   "Wanted %u, got %s" %
                                   (self.INITIAL_SIZE, s))

    def writeRead(self):
        # Perform a read and a write
        c = chr(ord('a') + random.randint(0, 25))
        self.host.execdom0("echo -n %s > /tmp/char" % (c))
        self.vdicommand("dd if=/tmp/char of=/dev/${DEVICE} bs=1 seek=%u" %
                        (self.INITIAL_SIZE - 1))
        self.host.execdom0("sync")
        data = self.vdicommand(\
            "dd if=/dev/${DEVICE} bs=1 skip=%u count=1 2>/dev/null" %
            (self.INITIAL_SIZE - 1)).strip()
        r = re.search(r"^([a-z])", data, re.MULTILINE)
        if not r or r.group(1) != c:
            raise xenrt.XRTFailure("Data write/read inconsistent")

    def run(self, arglist):
        if self.INITIAL_SIZE:
            if self.runSubcase("doCreate", (), "VDI", "Create") != \
                   xenrt.RESULT_PASS:
                return    
            if self.runSubcase("checkSize", (), "VDI", "Size") != \
                   xenrt.RESULT_PASS:
                return    
            if self.runSubcase("writeRead", (), "VDI", "WriteRead") != \
                   xenrt.RESULT_PASS:
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

    def vdicommand(self, command):
        sftp = self.host.sftpClient()
        sd = self.host.hostTempDir()
        t = xenrt.TempDirectory()
        
        s = "%s/cmd.sh" % (sd)
        filename = "%s/cmd.sh" % (t.path())
        
        file(filename, "w").write(command)
        sftp.copyTo("%s/cmd.sh" % (t.path()), s)
        self.host.execdom0("chmod +x %s" % (s))
        data = self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" %  
                                  (self.vdi, s))
        self.host.execdom0("rm -rf %s" % (sd))
        t.remove()
        return data

class _TCVDICreateRoundup(_TCVDICreate):
    """Base class for tests for the size in vdi-create not being rounded down"""

    INITIAL_SIZE = 4294967297

class TC8515(_TCVDICreateRoundup):
    """VDI create of a odd size LVM VDI should round up to the next allocation unit"""

    SRTYPE = "lvm"

class TC27157(_TCVDICreateRoundup):
    """VDI create of a odd size LVM VDI should round up to the next allocation unit"""

    SRTYPE = "lvmoiscsi"

class TC8520(_TCVDICreateRoundup):
    """VDI create of a odd size VHDoEXT VDI should round up to the next allocation unit"""

    SRTYPE = "ext"

class TC8523(_TCVDICreateRoundup):
    """VDI create of a odd size NFS VDI should round up to the next allocation unit"""
    
    SRTYPE = "nfs"

class TC20930(_TCVDICreateRoundup):
    """VDI create of a odd size filesr VDI should round up to the next allocation unit"""

    SRTYPE = "file"

class TC8524(_TCVDICreateRoundup):
    """VDI create of a odd size NetApp VDI should round up to the next allocation unit"""

    SRTYPE = "netapp"

class TC9419(_TCVDICreateRoundup):
    """VDI create of a odd size CVSM VDI should round up to the next allocation unit"""

    SRTYPE = "cslg"

class TC9936(TC9419):
    """VDI create of an odd size CVSM-FC VDI should round up to the next allocation unit"""
    
    SRTYPE = "cslg"

class TC8525(_TCVDICreateRoundup):
    """VDI create of a odd size Equallogic VDI should round up to the next allocation unit"""

    SRTYPE = "equal"

class TCCIFSOddSize(_TCVDICreateRoundup):
    """CIFS Odd size"""

    SRTYPE = "cifs"
    
class TCFCOEOddSize(_TCVDICreateRoundup):
    """FCoE SR Odd size"""

    SRTYPE = "lvmofcoe"
#############################################################################
# SR introduce testcases

class TC8537(xenrt.TestCase):
    """LVHD format detection on sr-introduce"""

    USE_VHD = True

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

    def prepare(self, arglist):

        self.lun = None
        self.sr = None
        self.vdi = None
        
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()

        if self.USE_VHD:
            smconfig = None
        else:
            smconfig = "type=raw"

        # Create a LVMoISCSI SR
        self.lun = xenrt.ISCSITemporaryLun(100)
        self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.host,
                                                                  "TC853x")
        if not self.USE_VHD:
            # Hack the SM to use a different name for the MGT volume
            self.host.execdom0("sed -e's/MDVOLUME_NAME = \"MGT\"/MDVOLUME_NAME = \"XenRTMGT\"/' -i /opt/xensource/sm/LVHDSR.py")
        try:
            self.sr.create(self.lun, subtype="lvm", findSCSIID=True, noiqnset=True)

            # Create a single VDI on the SR and write a pattern to it
            self.vdi = self.host.createVDI(4194304,
                                           sruuid=self.sr.uuid,
                                           smconfig=smconfig)
            size = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
            cmd = "%s/remote/patterns.py /dev/${DEVICE} %d write 1" % \
                  (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size)
            self.vdicommand(self.vdi, cmd)        

            # Forget the SR
            self.sr.forget()
        finally:
            if not self.USE_VHD:
                self.host.execdom0("sed -e's/MDVOLUME_NAME = \"XenRTMGT\"/MDVOLUME_NAME = \"MGT\"/' -i /opt/xensource/sm/LVHDSR.py")

    def run(self, arglist):

        # Introduce the SR and wait a little for the VDIs to be found
        self.sr.introduce()
        time.sleep(30)
        
        # Verify the VDI created above exists and can be read
        if not self.vdi in self.sr.listVDIs():
            raise xenrt.XRTFailure("VDI missing after SR introduce",
                                   self.vdi)
        size = long(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        cmd = "%s/remote/patterns.py /dev/${DEVICE} %d read 1" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size)
        self.vdicommand(self.vdi, cmd)

        if self.USE_VHD:
            # Verify the sm-config:use_vhd=true is set
            try:
                v = self.sr.paramGet("sm-config", "use_vhd")
            except:
                raise xenrt.XRTFailure("sm-config:use_vhd not set on "
                                       "introduced LVHD SR")
            if v != "true":
                raise xenrt.XRTFailure("sm-config:use_vhd=%s on "
                                       "introduced LVHD SR" % (v))
        else:
            # Verify the sm-config:use_vhd=true is set
            try:
                v = self.sr.paramGet("sm-config", "use_vhd")
            except:
                pass
            else:
                raise xenrt.XRTFailure("sm-config:use_vhd set on "
                                       "introduced legacy SR")
            
    def postRun(self):
        if self.sr:
            try:
                self.sr.remove()
            except:
                pass
        if self.lun:
            self.lun.release()
            
class TC8538(TC8537):
    """LVHD format detection on sr-introduce (legacy)"""

    USE_VHD = False
    
class TC8764(xenrt.TestCase):
    """/etc/lvm should not grow significantly when performing a large number of VDI create and destroy operations"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        srs = self.host.getSRs(type="lvm", local=True)
        if len(srs) == 0:
            raise xenrt.XRTError("No LVM SR found")
        self.sr = srs[0]
        self.host.waitForCoalesce(self.sr)

    def run(self, arglist):
        initialsize = int(self.host.execdom0("du -ks /etc/lvm").split()[0])
        for i in range(100):
            uuid = self.cli.execute("vdi-create",
                                    "sr-uuid=%s virtual-size=1GiB type=user "
                                    "name-label=tc87640%u" %
                                    (self.sr, i)).strip()
            self.cli.execute("vdi-destroy", "uuid=%s" % (uuid))
            if i % 10 == 9:
                time.sleep(60)
        finalsize = int(self.host.execdom0("du -ks /etc/lvm").split()[0])
        if finalsize < 100:
            pass
        else:
            if finalsize > (initialsize * 2) or finalsize > (initialsize + 200):
                raise xenrt.XRTFailure("/etc/lvm grew significantly while "
                                       "running VDI create/destroy loop")

class _SRSmokeTest(xenrt.TestCase):

    SRTYPE = None
    TESTMODE = False
    USEPOOL = True

    def __init__(self, tcid=None):
        self.sr = None
        self.host = None
        self.pool = None
        xenrt.TestCase.__init__(self, tcid=tcid)

    def createSR(self):
        raise xenrt.XRTError("Unimplemented")

    def destroySR(self):
        self.sr.destroy()
        self.sr.check()
        self.sr = None

    def forgetSR(self):
        self.sr.forget()

    def introduceSR(self):
        self.sr.introduce()
        self.sr.check()

    def install(self):
        self.guest = self.host.createGenericLinuxGuest(sr=self.sr.uuid)
        self.guest.check()

    def shutdown(self):
        self.guest.check()
        self.guest.shutdown()

    def start(self):
        self.guest.start()
        self.guest.check()

    def suspend(self):
        self.guest.check()
        self.host.genParamSet("host", 
                               self.host.getMyHostUUID(), 
                              "suspend-image-sr-uuid", 
                               self.sr.uuid)
        self.guest.suspend()

    def resume(self):
        self.guest.resume()
        self.guest.check()

    def reboot(self):
        self.guest.check()
        self.guest.reboot()
        self.guest.check()

    def snapshot(self):
        self.guest.check()
        snapuuid = self.guest.snapshot()
        self.guest.check()
        self.host.removeTemplate(snapuuid)

    def uninstall(self):
        self.guest.check()
        try: self.guest.shutdown()
        except: pass
        self.guest.uninstall()

    def localmigrate(self):
        self.guest.check()
        self.guest.migrateVM(self.host, live="true")
        self.guest.check()

    def pooltest(self):
        if not self.USEPOOL:
            raise xenrt.XRTSkip("Not using a pool")

        # Test starting a VM on a slave
        self.guest.check()
        self.guest.shutdown()
        self.guest.host = self.pool.getSlaves()[0]
        self.guest.start()
        self.guest.check()

        # Try and migrate it to the master
        self.guest.migrateVM(self.pool.master, live="true")
        self.guest.check()

        # Now reboot
        self.guest.reboot()
        self.guest.check()

        # Now migrate to the slave
        self.guest.migrateVM(self.pool.getSlaves()[0], live="true")
        self.guest.check()

        # Now suspend and resume
        self.guest.suspend()
        self.guest.resume()
        self.guest.check()

        # Finally migrate back to the master
        self.guest.migrateVM(self.pool.master, live="true")
        
    def run(self, arglist):
        self.guest = None
        
        # Create the SR
        if self.runSubcase("createSR", (), "SR", "create") \
               != xenrt.RESULT_PASS:
            return

        # Run subcases that perform VM operations using the SR
        subcasesVM = ["install",
                      "shutdown",
                      "start", 
                      "suspend",
                      "resume",
                      "localmigrate",
                      "pooltest",
                      "reboot",
                      "snapshot",
                      "uninstall"]
        # allowed-operations sometimes isn't populated immediately
        allowedops = None
        for i in range(3):
            data = self.host.genParamGet("sr", 
                                         self.sr.uuid,
                                         "allowed-operations")
            if data:
                allowedops = data.split("; ")
                break
            time.sleep(30)
        if allowedops == None:
            raise xenrt.XRTError("SR allowed-operations not populated",
                                 self.sr.uuid)
        xenrt.TEC().logverbose("Allowed operations: %s" % (allowedops))
        if not "VDI.snapshot" in allowedops: 
            subcasesVM.remove("snapshot")
        if self.TESTMODE:
            subcasesVM = []
        for case in subcasesVM:
            self.sr.check()
            result = self.runSubcase(case, (), "VM", case)
            if result != xenrt.RESULT_PASS and result != xenrt.RESULT_SKIPPED:
                break

        # Make sure the VM is halted
        if self.guest and self.guest.getState() != "DOWN":
            try:
                self.guest.shutdown(again=True)
            except Exception, e:
                xenrt.TEC().warning("Exception shutting down VM after "
                                    "lifecycle tests: %s" % (str(e)))

        # Forget and then reintroduce the SR
        if self.runSubcase("forgetSR", (), "SR", "forget") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("introduceSR", (), "SR", "introduce") \
               != xenrt.RESULT_PASS:
            return

        # Destroy the SR
        if self.runSubcase("destroySR", (), "SR", "destroy") \
               != xenrt.RESULT_PASS:
            return

    def postRun(self):
        try:
            if self.sr:
                self.sr.remove()
        except: pass

class TC9050(_SRSmokeTest):
    """Smoke test a NetApp over CVSM SR."""

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.cvsmserver = xenrt.CVSMServer(xenrt.TEC().registry.guestGet("CVSMSERVER"))
        self.sr = xenrt.lib.xenserver.CVSMStorageRepository(self.host,
                                                                 "cslgsr")
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        self.netapp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.cvsmserver.addStorageSystem(self.netapp)

    def createSR(self):
        for h in self.pool.getSlaves():
            self.sr.prepareSlave(self.pool.master, h)
        self.sr.create(self.cvsmserver,
                       self.netapp,
                       protocol="iscsi",
                       physical_size=None)

    def postRun(self):
        _SRSmokeTest.postRun(self)
        try: self.cvsmserver.removeStorageSystem(self.netapp)
        except: pass
        try: self.netapp.release()
        except: pass

class TC12687(TC9050):
    """Smoke test a NetApp over Integrated StorageLink/CVSM SR."""

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        self.netapp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)

    def createSR(self):
        for h in self.pool.getSlaves():
            self.sr.prepareSlave(self.pool.master, h)
        self.sr.create(self.netapp,
                       protocol="iscsi",
                       physical_size=None)
        self.host.pool.addSRToPool(self.sr, default=True)

    def postRun(self):
        _SRSmokeTest.postRun(self)
        try: self.netapp.release()
        except: pass

class TC13980(TC12687):
    """Smoke test an Equallogic adapter over Integrated StorageLink/CVSM SR."""

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_EQL_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_EQL_MAXSIZE", 1000000))
        self.eqlt = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)

    def createSR(self):
        for h in self.pool.getSlaves():
            self.sr.prepareSlave(self.pool.master, h)
        self.sr.create(self.eqlt,
                       protocol="iscsi",
                       physical_size=None)
        self.host.pool.addSRToPool(self.sr, default=True)

    def postRun(self):
        _SRSmokeTest.postRun(self)
        try: self.eqlt.release()
        except: pass

class TC14926(TC9050):
    """Smoke test an iSCSI SMI-S adapter over Integrated StorageLink/CVSM SR."""

    PROTOCOL="iscsi"

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_SMIS_ISCSI_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_SMIS_ISCSI_MAXSIZE", 1000000))
        self.smis = xenrt.SMISiSCSITarget()

    def createSR(self):
        for h in self.pool.getSlaves():
            self.sr.prepareSlave(self.pool.master, h)
        self.sr.create(self.smis,
                       protocol=self.PROTOCOL,
                       physical_size=None)
        self.host.pool.addSRToPool(self.sr, default=True)

    def postRun(self):
        _SRSmokeTest.postRun(self)
        try: self.smis.release()
        except: pass

class TC15174(TC14926):
    """Smoke test an FC SMI-S adapter over Integrated StorageLink/CVSM SR."""

    PROTOCOL="fc"

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")
        minsize = int(self.host.lookup("SR_SMIS_FC_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_SMIS_FC_MAXSIZE", 1000000))
        self.smis = xenrt.SMISFCTarget()

class _TC9081(_SRSmokeTest):
    """Smoke test a NetApp SR using secure control path"""

    PORT_TO_USE = 443
    PORT_TO_BLOCK = 80
    USEPOOL = False
    ARGS = None

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.sr = xenrt.lib.xenserver.NetAppStorageRepository(self.host,
                                                              "NAppUseHttps")
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 1000000))
        self.netapp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)

        # Block a port on the host to ensure we use the other port
        try: self.host.execdom0("service iptables restart")
        except: pass
        self.host.execdom0("iptables -I OUTPUT -p tcp -m tcp "
                           "-d %s --dport %u -j DROP" %
                           (self.netapp.getTarget(), self.PORT_TO_BLOCK))

        # Count traffic on the port we want
        self.host.execdom0("iptables -I OUTPUT -p tcp -m tcp "
                           "-d %s --dport %u" %
                           (self.netapp.getTarget(), self.PORT_TO_USE))
        
    def createSR(self):
        self.sr.create(self.netapp, options=self.ARGS)
        # Check the packets went the way we wanted
        data = self.host.execdom0("iptables -L OUTPUT -v -n -x")
        packets = {}
        for line in data.splitlines():
            l = line.strip().split()
            if len(l) >= 10:
                r = re.search("dpt:(\d+)", l[-1])
                if r:
                    packets[r.group(1)] = int(l[0])
        if not packets.has_key(str(self.PORT_TO_BLOCK)):
            raise xenrt.XRTError("Did not find packet count for port %u" %
                                 (self.PORT_TO_BLOCK))
        if packets[str(self.PORT_TO_BLOCK)] != 0:
            raise xenrt.XRTFailure("Traffic to the filer port %u was seen" %
                                   (self.PORT_TO_BLOCK))
        if not packets.has_key(str(self.PORT_TO_USE)):
            raise xenrt.XRTError("Did not find packet count for port %u" %
                                 (self.PORT_TO_USE))
        if packets[str(self.PORT_TO_USE)] == 0:
            raise xenrt.XRTFailure("Did not see traffic to the filer port %u" %
                                   (self.PORT_TO_USE))

    def postRun(self):
        _SRSmokeTest.postRun(self)
        try: self.netapp.release()
        except: pass
        try: self.host.execdom0("service iptables restart")
        except: pass
        
class TC9081(_TC9081):
    """Operation of NetApp SR using HTTPS for the control path"""

    PORT_TO_USE = 443
    PORT_TO_BLOCK = 80
    ARGS = "usehttps=true"

class TC9082(_TC9081):
    """Operation of NetApp SR using HTTP for the control path"""

    PORT_TO_USE = 80
    PORT_TO_BLOCK = 443
    ARGS = "usehttps=false"

class TC9083(_TC9081):
    """Operation of NetApp SR using default (HTTP) for the control path"""

    PORT_TO_USE = 80
    PORT_TO_BLOCK = 443
    ARGS = None

class TC9351(_SRSmokeTest):
    """NetApp over CVSM (using FC) smoke test"""

    def prepare(self, arglist):
        self.fcarray = xenrt.FCHBATarget()        
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        try:
            self.host.execdom0("iptables -I OUTPUT -d %s -p tcp --destination-port 3260 -j DROP" % (self.fcarray.getTarget()))
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception blocking iscsi traffic: %s" % (str(e)))
        self.cvsmserver = xenrt.CVSMServer(xenrt.TEC().registry.guestGet("CVSMSERVER"))
        self.sr = xenrt.lib.xenserver.CVSMStorageRepository(self.host,
                                                                 "cslgsr")
        self.cvsmserver.addStorageSystem(self.fcarray)

    def createSR(self):
        for h in self.pool.getSlaves():
            self.sr.prepareSlave(self.pool.master, h)
        try:
            self.sr.create(self.cvsmserver,
                           self.fcarray,
                           protocol="fc",
                           physical_size=None)
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Error trying to create the SR of type cslg: " % (str(e)))
    def postRun(self):
        _SRSmokeTest.postRun(self)
        try:
            self.host.execdom0("iptables -D OUTPUT -d %s -p tcp --destination-port 3260 -j DROP" % (self.fcarray.getTarget()))
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception un-blocking iscsi traffic: %s" % (str(e)))
        try: 
            self.cvsmserver.removeStorageSystem(self.fcarray)
        except Exception,e: 
            xenrt.TEC().warning("Exception removing Storage System: %s" % (str(e)))
        try: 
            self.fcarray.release()
        except Exception,e: 
            xenrt.TEC().warning("Exception releaseing resource: %s" % (str(e)))

class TC12688(TC9351):
    """NetApp over Integrated StorageLink/CVSM (using FC) smoke test"""

    def prepare(self, arglist):
        self.fcarray = xenrt.FCHBATarget()        
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        try:
            self.host.execdom0("iptables -I OUTPUT -d %s -p tcp --destination-port 3260 -j DROP" % (self.fcarray.getTarget()))
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception blocking iscsi traffic: %s" % (str(e)))
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")

    def createSR(self):
        for h in self.pool.getSlaves():
            self.sr.prepareSlave(self.pool.master, h)
        try:
            self.sr.create(self.fcarray,
                           protocol="fc",
                           physical_size=None)
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Error trying to create the SR of type cslg: %s" % (str(e)))
        self.host.pool.addSRToPool(self.sr, default=True)

    def postRun(self):
        _SRSmokeTest.postRun(self)
        try:
            self.host.execdom0("iptables -D OUTPUT -d %s -p tcp --destination-port 3260 -j DROP" % (self.fcarray.getTarget()))
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception un-blocking iscsi traffic: %s" % (str(e)))
        try: 
            self.fcarray.release()
        except Exception,e: 
            xenrt.TEC().warning("Exception releaseing resource: %s" % (str(e)))

class TC13982(TC12688):
    """Equallogic over Integrated StorageLink/CVSM (using FC) smoke test"""

    def prepare(self, arglist):
        self.fcarray = xenrt.FCHBATarget()        
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        try:
            self.host.execdom0("iptables -I OUTPUT -d %s -p tcp --destination-port 3260 -j DROP" % (self.fcarray.getTarget()))
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception blocking iscsi traffic: %s" % (str(e)))
        self.sr = xenrt.lib.xenserver.IntegratedCVSMStorageRepository(self.host,
                                                                           "cslgsr")

    def createSR(self):
        for h in self.pool.getSlaves():
            self.sr.prepareSlave(self.pool.master, h)
        try:
            self.sr.create(self.fcarray,
                           protocol="fc",
                           physical_size=None)
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Error trying to create the SR of type cslg: %s" % (str(e)))
        self.host.pool.addSRToPool(self.sr, default=True)

    def postRun(self):
        _SRSmokeTest.postRun(self)
        try:
            self.host.execdom0("iptables -D OUTPUT -d %s -p tcp --destination-port 3260 -j DROP" % (self.fcarray.getTarget()))
        except Exception,e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().warning("Exception un-blocking iscsi traffic: %s" % (str(e)))
        try: 
            self.fcarray.release()
        except Exception,e: 
            xenrt.TEC().warning("Exception releaseing resource: %s" % (str(e)))

class TC10601(xenrt.TestCase):
    """The default disk scheduler for a disk underlying a local ext SR should be "cfq"."""

    SRTYPE = "ext"
    SCHEDULER = "cfq"

    def run(self, arglist):

        # Find a suitable SR
        host = self.getDefaultHost()
        
        gd = host.lookup("OPTION_GUEST_DISKS", None)
        if gd and host.lookup("OPTION_CARBON_DISKS", None) != gd:
            # CA-116302
            self.SCHEDULER = "noop"
        
        srs = host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        sr = srs[0]
        
        # Check the SR has no manually set disk scheduler
        scheduler = None
        try:
            scheduler = host.genParamGet("sr", sr, "other-config", "scheduler")
        except:
            pass
        if scheduler:
            raise xenrt.XRTError(\
                "Cannot run testcase on SR with scheduler set",
                scheduler)

        # Read the underlying scheduler for the device
        pbds = host.minimalList("pbd-list", args="sr-uuid=%s" % (sr))
        for p in pbds:
            device = host.genParamGet("pbd", p, "device-config", pkey="device")
            devicename = host.execdom0("readlink -f %s" % (device)).strip()
            if devicename.startswith("/dev/"):
                devicename = re.match("/dev/(?P<base>\D+)",
                                      devicename).group("base")
            devicename = devicename.replace("/", "!")
            data = host.execdom0("cat /sys/block/%s/queue/scheduler" %
                                 (devicename)).strip()
            if not re.search("\[%s\]" % (self.SCHEDULER), data):
                raise xenrt.XRTFailure(\
                    "Unexpected scheduler: Expected %s Got %s" %
                    (self.SCHEDULER, data))         

class TC10602(TC10601):
    """The default disk scheduler for a disk underlying a local LVM SR should be "cfq"."""

    SRTYPE = "lvm"

class TC10671(xenrt.TestCase):
    """A freshly created VDI should contain entirely zero data (LVM)"""

    SRTYPE = "lvm"
    SIZE = 8 * xenrt.GIGA

    def run(self, arglist):
        self.vdi = None
        self.host = self.getDefaultHost()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        sr = srs[0]
        self.vdi = self.host.createVDI(self.SIZE, sruuid=sr)
        vsize = int(self.host.genParamGet("vdi", self.vdi, "virtual-size"))
        if vsize < self.SIZE:
            raise xenrt.XRTError("VDI virtual-size is less than we asked for",
                                 str(vsize))
        filename = self.host.hostTempFile()
        try:
            self.host.execdom0("chmod +x %s" % (filename))
            self.host.execdom0(\
                "echo 'dd if=/dev/${DEVICE} 2>/dev/null | sum' > %s" %
                (filename))
            data = self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" %
                                      (self.vdi, filename),
                                      timeout=1200)
            sum = None
            for line in data.splitlines():
                if line.startswith("DEVICE="):
                    continue
                sum = int(line.split()[0])
                break
            if sum == None:
                raise xenrt.XRTError("Could not parse sum output from "
                                     "with-vdi call")
            if sum != 0:
                raise xenrt.XRTFailure("VDI contains some non-zero data")
        finally:
            self.host.execdom0("rm -f %s" % (filename))

    def postRun(self):
        if self.vdi:
            self.host.destroyVDI(self.vdi)

class TC10672(TC10671):
    """A freshly created VDI should contain entirely zero data (file based VHD)"""

    SRTYPE = "ext"

class TC27093(TC10671):
    """A freshly created VDI should contain entirely zero data (file based VHD)"""

    SRTYPE = "btrfs"


class TC27185(TC10671):
    """A freshly created VDI should contain entirely zero data (file based VHD)"""

    SRTYPE = "rawnfs"


class TC10673(TC10671):
    """A freshly created VDI should contain entirely zero data (Equallogic thin provisioning)"""

    SRTYPE = "equal"

class TC10674(TC10671):
    """A freshly created VDI should contain entirely zero data (Equallogic thick provisioning)"""

    SRTYPE = "equal"

class TC10679(TC10671):
    """A freshly created VDI should contain entirely zero data (NetApp thin provisioning)"""

    SRTYPE = "netapp"

class TC10680(TC10671):
    """A freshly created VDI should contain entirely zero data (NetApp thick provisioning)"""

    SRTYPE = "netapp"

class TCCIFSZeroedContents(TC10671):
    """CIFS Zeroed contents"""

    SRTYPE = "cifs"

class TCFCOEZeroedContents(TC10671):
    """FCoE SR Zeroed contents"""

    SRTYPE = "lvmofcoe"
    
# New Test cases added for copying from one host to another 

class TC12158(_VDICopy):
    """Verify vdi-copy between lvm SR on slave host and an ext SR on master hosts"""
    FROM_TYPE = "lvm"
    TO_TYPE = "ext"
    HOST_TYPE = "slavetomaster"
    SAME_HOSTS  = False

class TC12159(_VDICopy):
    """Verify vdi-copy between lvm SR on slave host and an ext SR on slave hosts"""
    FROM_TYPE = "lvm"
    TO_TYPE = "ext"
    HOST_TYPE = "slavetoslave"
    SAME_HOSTS  = False

class TC12160(_VDICopy):
    """Verify vdi-copy between lvm SR on master host and an ext SR on slave hosts"""
    FROM_TYPE = "lvm"
    TO_TYPE = "ext"
    HOST_TYPE = "mastertoslave"
    SAME_HOSTS  = False

class TC12161(_VDICopy):
    """Verify vdi-copy between lvm SR on slave host and an lvm SR on master hosts"""
    FROM_TYPE = "lvm"
    TO_TYPE = "lvm"
    HOST_TYPE = "slavetomaster"
    SAME_HOSTS  = False

class TC12162(_VDICopy):
    """Verify vdi-copy between lvm SR on slave host and an lvm SR on slave hosts"""
    FROM_TYPE = "lvm"
    TO_TYPE = "lvm"
    HOST_TYPE = "slavetoslave"
    SAME_HOSTS  = False

class TC12163(_VDICopy):
    """Verify vdi-copy between lvm SR on master host and an lvm SR on slave hosts"""
    FROM_TYPE = "lvm"
    TO_TYPE = "lvm"
    HOST_TYPE = "mastertoslave"
    SAME_HOSTS  = False

class TC12164(_VDICopy):
    """Verify vdi-copy between ext SR on slave host and an ext SR on master hosts"""
    FROM_TYPE = "ext"
    TO_TYPE = "ext"
    HOST_TYPE = "slavetomaster"
    SAME_HOSTS  = False

class TC12165(_VDICopy):
    """Verify vdi-copy between ext SR on slave host and an ext SR on slave hosts"""
    FROM_TYPE = "ext"
    TO_TYPE = "ext"
    HOST_TYPE = "slavetoslave"
    SAME_HOSTS  = False

class TC12166(_VDICopy):
    """Verify vdi-copy between ext SR on master host and an ext SR on slave hosts"""
    FROM_TYPE = "ext"
    TO_TYPE = "ext"
    HOST_TYPE = "mastertoslave"
    SAME_HOSTS  = False

class TC12167(_VDICopy):
    """Verify vdi-copy between ext SR on slave host and lvm SR on master hosts"""
    FROM_TYPE = "ext"
    TO_TYPE = "lvm"
    HOST_TYPE = "slavetomaster"
    SAME_HOSTS  = False

class TC12168(_VDICopy):
    """Verify vdi-copy between ext SR on slave host and lvm SR on slave hosts"""
    FROM_TYPE = "ext"
    TO_TYPE = "lvm"
    HOST_TYPE = "slavetoslave"
    SAME_HOSTS  = False

class TC12169(_VDICopy):
    """Verify vdi-copy between ext SR on master host and lvm SR on slave hosts"""
    FROM_TYPE = "ext"
    TO_TYPE = "lvm"
    HOST_TYPE = "mastertoslave"
    SAME_HOSTS  = False

class TC13476(xenrt.TestCase):
    """All physical volumes on 'ext' SR should be spanned by one single volume group."""

    def prepare(self, arglist = []):
        self.host = self.getDefaultHost()
        # check that multiple hard drives are visible
        xenrt.TEC().logverbose("Checking number of hard drives")
        diskList = self.host.execdom0("pvs").strip()
        nDisks = len(diskList.split("\n")) - 1
        xenrt.TEC().logverbose("Found %s hard drives." % nDisks)
        if nDisks < 2:
            raise xenrt.XRTError("Expected at least two physical hard drive on the host.")

    def run(self, arglist=[]):
        # check that vgs command returns only one volume group
        vgList =  self.host.execdom0("vgs").strip()
        nVGs = len(vgList.split("\n")) - 1
        if nVGs > 1:
            raise xenrt.XRTError("Single voulume group expected! Found: \n%s" % vgList)

class TC13568(xenrt.TestCase):
    """Test VDIs don't get corrupted after network outage (CA-56857)"""
    
    def run(self, arglist):
        pool = self.getDefaultPool()
        master = pool.master
        slave = pool.getSlaves()[0]
        sr = master.getSRs(type="lvmoiscsi")[0]
        
        # create vm on slave
        g = slave.createGenericLinuxGuest(sr=sr)
        
        # use this script on slave to simulate slave-host network 
        # outage and then to check for the slave opaque-ref
        # in the VDI sm-config.
        
        scr = """#!/usr/bin/python
import sys, time, os, XenAPI

# simulate network outage
os.system("iptables -F")
os.system("iptables -X")
os.system("iptables -P INPUT DROP")
os.system("iptables -P OUTPUT DROP")
os.system("iptables -P FORWARD DROP")
os.system("service iptables save")

# wait 11 mins
time.sleep(660)

# bring network back
os.system("iptables -F")
os.system("iptables -X")
os.system("iptables -P INPUT ACCEPT")
os.system("iptables -P OUTPUT ACCEPT")
os.system("iptables -P FORWARD ACCEPT")
os.system("service iptables save")

session=XenAPI.xapi_local()

session.xenapi.login_with_password("root","")
vm_refs_recs = session.xenapi.VM.get_all_records()
vbd_refs_recs = session.xenapi.VBD.get_all_records()
vdi_refs_recs = session.xenapi.VDI.get_all_records()
sr_refs_recs = session.xenapi.SR.get_all_records()

vm_refs = vm_refs_recs.keys()
vbd_refs = vbd_refs_recs.keys()
vdi_refs = vdi_refs_recs.keys()
sr_refs = sr_refs_recs.keys()

powered_on_vms = [vm_ref for vm_ref in vm_refs if vm_refs_recs[vm_ref]['power_state']=='Running']

error=0

def check_vdi(vdi,host):
	global error
	sr=vdi_refs_recs[vdi]['SR']
	sr_type=sr_refs_recs[sr]['type']
	if sr_type in ['lvmoiscsi','lvmohba','nfs','lvm','ext']:
		print "Checking VDI: %s (%s)" % (vdi_refs_recs[vdi]['name_label'], vdi_refs_recs[vdi]['uuid'])
		if ("host_%s" % host) in vdi_refs_recs[vdi]['sm_config']:
			print "VDI OK:%s" % (vdi_refs_recs[vdi]['uuid'])
		else:
			print "Host key not found:%s" % (vdi_refs_recs[vdi]['uuid'])
			error += 1
	else:
		print "SR type OK. Skipping check of VDI: %s (%s)" % (vdi_refs_recs[vdi]['name_label'], vdi_refs_recs[vdi]['uuid'])

def check_vm(vm):
	print "Checking VM %s" % vm_refs_recs[vm]['name_label']
	my_vbds = [vbd_ref for vbd_ref in vbd_refs if vbd_refs_recs[vbd_ref]['VM']==vm]
	my_vdis = map( lambda vbd: vbd_refs_recs[vbd]['VDI'], my_vbds)
	host = vm_refs_recs[vm]['resident_on']
	for vdi in my_vdis:
		if vdi and len(vdi) > 0:
			check_vdi(vdi,host)

for vm in powered_on_vms:
	check_vm(vm)

if error > 0:
	print "*********************"
	print "** ERROR DETECTED  **"
	print "*********************"
	sys.exit(1)
else:
	print "No errors detected"
"""
    
        # write script to temp file on controller
        dir = xenrt.TEC().tempDir()
        tempFile = dir + "/TC13568"
        f = open(tempFile, "w")
        f.write(scr)
        f.close()
        
        # copy script to slave
        sftp = slave.sftpClient()
        try:
            sftp.copyTo(tempFile, "/root/TC13568")
        finally:
            sftp.close()
            
        # take guest offline for 11 mins using script
        slave.execdom0("chmod +x /root/TC13568")
        
        try:
            slave.execdom0("/root/TC13568 > /tmp/TC13568")
        except: 
            # this will time out as networking will go down
            pass
    
        # wait 12 mins for slave to come back
        time.sleep(720)
        
        # check guest is still powered on
        if g.getState() != "UP":
            raise xenrt.XRTError("VM didn't stay up after simulated network outage")
        
        # get script output from slave.
        scrRet = slave.execdom0("cat /tmp/TC13568")
        
        if re.search(r"ERROR DETECTED", scrRet):
            raise xenrt.XRTError("host keys not present after simulated network outage")
        
        vbdCount = g.countVBDs()
        
        if vbdCount < 1:
            raise xenrt.XRTError("VM has no VBDs after simulated network outage")
        
        # now check all lvmoiscsi VDIs on the VM
        vdiCount = 0
        for i in range(vbdCount):
            vdiuuid = g.getDiskVDIUUID(str(i))
            
            if not vdiuuid or len(vdiuuid) <= 0:
                raise xenrt.XRTError("Could not get VDI UUID after simulated network outage")
                
            vdiSr = slave.getVDISR(vdiuuid)
            
            if not vdiSr or len(vdiSr) <= 0:
                raise xenrt.XRTError("Could not get VDI SR UUID after simulated network outage")
            
            if vdiSr == sr:
                vdiCount = vdiCount + 1
                
                # check for VDI OK:uuid from script output
                
                if not re.search(r"VDI OK:" + vdiuuid, scrRet):
                    raise xenrt.XRTError("Could not get VDI host key after simulated network outage")
                
        if vdiCount < 2:
            raise xenrt.XRTError("Could not get VDIs after simulated network outage")
           
class TC17360(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        # Get the Default host 
        self.host = self.getDefaultHost()   
        
        # Set up a NetApp SR
        minsize = int(self.host.lookup("SR_NETAPP_MINSIZE", 40))
        maxsize = int(self.host.lookup("SR_NETAPP_MAXSIZE", 10000000))
        napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
        self.sr = xenrt.lib.xenserver.NetAppStorageRepository(self.host, "NetappSR")
        if self.host.lookup("USE_MULTIPATH",False,boolean = True):
            mp = True
        else: 
            mp =None
        self.sr.create(napp, options=None, multipathing=mp) 
        
        #throw error if their was a failure in creating SR
        self.sr.check()
        return
   
    
    def run(self, arglist=None):
     
        noOfVdis = 10  # Creating 10 VDI's
        size = 400      # Each VDI of size 400B
            
        # Create noOfVdis on NetappSr append them to actualVdis.
        actualVdis = [self.host.createVDI(size, sruuid=self.sr.uuid, name="VDI_%s" % i)for i in range(noOfVdis)]

        # forget NetappSR - pbd unplug and sr-forget
        self.host.forgetSR(self.sr.uuid)  
        
        # Introduce the SR and wait a little for the VDIs to be found
        self.sr.introduce()
        time.sleep(100)
        
        # check whether each of the VDI's which were their before forgetting are there even after introducing
        VDIs_present = set(self.sr.listVDIs())
        VDIs_missing = filter(lambda vdi: vdi not in VDIs_present, VDIs_present)

        for vdi in VDIs_missing:
            xenrt.TEC().logverbose("VDI %s is missing after SR introduce" % vdi)
            
        if len(VDIs_missing) > 0:
            raise xenrt.XRTFailure("VDIs are missing after SR introduce")
            
    def postRun(self):
        
        self.sr.remove()
        return


class TC17896(xenrt.TestCase):
    """ XML parser breaks when parsing the metadata VDI which contains special characters  """
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        cli = self.host.getCLIInstance()

        self.sruuid = self.host.minimalList("sr-list name-label=lvmoiscsisr")[0]
        self.host.createVDI(8 * xenrt.MEGA, sruuid=self.sruuid, name="m&s")

    def run(self, arglist=None):
        try:
            self.host.createVDI(8 * xenrt.MEGA, sruuid=self.sruuid, name="failure-trigger")
            self.host.createVDI(8 * xenrt.MEGA, sruuid=self.sruuid, name="failure-trigger")
            self.host.createVDI(8 * xenrt.MEGA, sruuid=self.sruuid, name="failure-trigger")
        except:
            raise xenrt.XRTFailure("Possible regression in the use of untreated special chars")

class TC17895(xenrt.TestCase):
    """vbd-unplug fails with timeout instead of an error """

    def prepare(self, arglist=None):
        host = self.getDefaultHost()
        self.cli = host.getCLIInstance()
        guest = self.getGuest("linux")

        log("Create VDI")
        vdiuuid = host.createVDI(xenrt.GIGA, sruuid=host.lookupDefaultSR(), name="XenRT-VDI")

        log("Attach vdi to guest named \"linux\"")
        self.vbduuid = self.cli.execute("vbd-create vm-uuid=%s vdi-uuid=%s device=autodetect" % (guest.getUUID(), vdiuuid), strip=True)
        self.cli.execute("vbd-plug uuid=%s" % (self.vbduuid))

        time.sleep(10)

        log("Create file-system and mount")
        device = host.minimalList("vbd-list uuid=%s params=device" % self.vbduuid)[0]
        guest.execguest("mkfs.ext3 /dev/%s" % device)
        guest.execguest("mount /dev/%s /media" % device)

    def run(self, arglist=None):
        
        log("Try unplugging VBD")
        try:
            self.cli.execute("vbd-unplug uuid=%s" % self.vbduuid)
        except Exception, ex:
            xenrt.TEC().logverbose("Exception: " + str(ex))

        before = int(time.time())
        log("Start timer and try unplugging VBD again")
        try:
            self.cli.execute("vbd-unplug uuid=%s" % self.vbduuid, timeout=16*60)
        except Exception, ex:
            xenrt.TEC().logverbose("Exception: " + str(ex))

        now = int(time.time())

        if (now - before) > 15*60:
            raise xenrt.XRTFailure("VBD unplug timed-out when it should have failed fast with error.")

class TC19050(xenrt.TestCase):
    """Verifying leaf-coalesce when the tapdisk is paused (HFX-645)"""

    DISK_SIZE = 200 * xenrt.GIGA # 200GB Disk

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        self.sruuid = self.host.lookupDefaultSR()
        self.vdiuuid = self.host.createVDI(self.DISK_SIZE, sruuid=self.sruuid, name="XenRT-VDI")
        self.vmuuid = self.host.getMyDomain0UUID()
        self.vbduuid = self.cli.execute("vbd-create vm-uuid=%s vdi-uuid=%s device=autodetect" % (self.vmuuid, self.vdiuuid), strip=True)
        self.cli.execute("vbd-plug uuid=%s" % (self.vbduuid))
 
        time.sleep(10)
 
        self.device = self.host.minimalList("vbd-list uuid=%s params=device" % self.vbduuid)[0]
        self.host.execdom0("mkfs.ext3 /dev/%s" % self.device)
        self.host.execdom0("mount /dev/%s /media" % self.device)

        # Script to continuously allocate the attached disk.
        writeScript = """#!/bin/bash
# to fully allocate the disk.
dd if=/dev/zero of=/media/delete_me bs=1M
touch write_done.dat"""

        self.host.execdom0("echo '%s' > script.sh; exit 0" % writeScript)
        self.host.execdom0("chmod a+x script.sh; exit 0")

        before = int(time.time())
        self.host.execdom0("/root/script.sh < /dev/null > script.log 2>&1 &")
        # Wait until the whole disk is fully allocated.
        while True:
            if self.host.execdom0("test -e write_done.dat", retval="code") != 1:
                break
            xenrt.sleep(30)
        now = int(time.time())
        xenrt.TEC().logverbose("Time taken to fully allocate the disk [%dGB] is %d minutes" % (self.DISK_SIZE, (now - before)/60))

    def run(self, arglist=None):

        filename = "/dev/VG_XenStorage-%s/VHD-%s" % (self.sruuid,self.vdiuuid)

        xenrt.TEC().logverbose("Timing leaf-coalesce without B clause. (without using HFX-645 fix)")
        before = int(time.time())
        try:
            self.host.execdom0("time vhd-util check -n %s" % filename)
        except Exception, e:
            raise xenrt.XRTError("Exception while checking leaf-coalesce time: %s" % str(e))
        now = int(time.time())
        xenrt.TEC().logverbose("Time taken to leaf-coalesce without blktap fix is %d seconds" % (now - before))

        xenrt.TEC().logverbose("Timing leaf-coalesce with B clause. (using HFX-645 fix)")
        before = int(time.time())
        try:
            self.host.execdom0("time vhd-util check -n %s -B" % filename)
        except Exception, e:
            raise xenrt.XRTError("Exception while checking leaf-coalesce time: %s" % str(e))
        now = int(time.time())
        xenrt.TEC().logverbose("Time taken to leaf-coalesce with blktap fix is %d seconds" % (now - before))

        if (now - before) > 10: # 10 seconds
            raise xenrt.XRTFailure("Error, leaf-coalesce took more time than expected. time taken %d" % (now - before))

class TC19276(xenrt.TestCase):
    """Verify VHD coalesce utility handle smaller ancestors correctly (SCTX-1240)"""

    DISK_SIZE = 20 * xenrt.GIGA # 20GB Disk

    def writePattern(self, params, fileid):
        """Script to write some patterns to attached disk."""

        vgname = "VG_XenStorage-%s" % self.sruuid
        lvname = "VHD-%s" % self.vdiuuid
        lvpath = "/dev/%s/%s" % (vgname, lvname)

        tapdiskminor = int(self.host.execdom0("tap-ctl list | grep %s | awk '{print $2}' | awk -F= '{print $2}'" %
                                                                                                        lvpath).strip())
        tapdiskpath = "/dev/xen/blktap-2/tapdev%d" % tapdiskminor

        writeScript = """#!/bin/bash
dd if=/dev/zero of=%s %s oflag=direct
touch write_done_%d.dat""" % (tapdiskpath, params.strip(), fileid)

        self.host.execdom0("echo '%s' > script_%d.sh; exit 0" % (writeScript, fileid))
        self.host.execdom0("chmod a+x script_%d.sh; exit 0" % fileid)
        self.host.execdom0("/root/script_%d.sh < /dev/null > script_%d.log 2>&1 &" % (fileid, fileid))

        # Wait until the writting is complete.
        deadline = xenrt.util.timenow() + 9000 # 2.5 hours
        while True:
            if self.host.execdom0("test -e write_done_%d.dat" % fileid, retval="code") != 1:
                break
            if xenrt.util.timenow() > deadline:
                xenrt.TEC().warning("Timed out waiting for the pattern to be written to disk.")
                break
            xenrt.sleep(30)

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()

        # Create a VDI of a certain size (say DISK_SIZE) and attach it to VM
        self.sruuid = self.host.lookupDefaultSR()
        self.vdiuuid = self.host.createVDI(self.DISK_SIZE, sruuid=self.sruuid, name="XenRT-VDI")
        self.guest = self.host.createGenericLinuxGuest()

        self.vbduuid = self.cli.execute("vbd-create vm-uuid=%s vdi-uuid=%s device=autodetect" %
                                                                (self.guest.getUUID(), self.vdiuuid), strip=True)
        self.cli.execute("vbd-plug uuid=%s" % (self.vbduuid))
        time.sleep(10)

    def run(self, arglist=None):

        vdiSize = long(self.host.genParamGet("vdi", self.vdiuuid, "virtual-size"))
        xenrt.TEC().logverbose("[Before Resize] VDI Size %u" % vdiSize)

        # Writting 1GB of pattern from the begining of the block device.
        ddPattern = "bs=1024 count=1000000"
        self.writePattern(ddPattern, 1)

        # Snapshot the VDI (create snapshot S1)
        snap1uuid = self.cli.execute("vdi-snapshot uuid=%s" % self.vdiuuid).strip()

        # Writting another 1GB of pattern starting from the last left position.
        ddPattern = "bs=1024 count=1000000 seek=1000001"
        self.writePattern(ddPattern, 2)

        # Resize the VDI to a larger size, but do not write into it.
        self.cli.execute("vbd-unplug uuid=%s" % (self.vbduuid))
        self.cli.execute("vdi-resize", "uuid=%s disk-size=%d" % (self.vdiuuid, (2*self.DISK_SIZE)))
        self.cli.execute("vbd-plug uuid=%s" % (self.vbduuid))
        time.sleep(10)

        vdiSize = long(self.host.genParamGet("vdi", self.vdiuuid, "virtual-size"))
        xenrt.TEC().logverbose("[After Resize] VDI Size %u" % vdiSize)

        # Snapshot the VDI again.(create snapshot S2)
        snap2uuid = self.cli.execute("vdi-snapshot uuid=%s" % self.vdiuuid).strip()

        # Write a few KB (but less than 1MB) into the end of the VDI, into the offset that would've been beyond the original size
        xenrt.TEC().logverbose("Writing 80KB of pattern beyond the original size.")
        ddPattern = "bs=1024 count=80 seek=21000000"
        self.writePattern(ddPattern, 3)

        # Snapshot the VDI again.(create snapshot S3)
        snap3uuid = self.cli.execute("vdi-snapshot uuid=%s" % self.vdiuuid).strip()

        # Listing the number of VHDs in the SR before the snapshot delete.
        beforeDeleteNumberOfVHDs = self.host.listVHDsInSR(self.sruuid)
        xenrt.TEC().logverbose("[Before Snapshot Delete] Number of VHDs in the default SR is %d" %
                                                                            len(beforeDeleteNumberOfVHDs))

        # Delete snapshot S2 and wait for the coalesce to complete
        self.cli.execute("vdi-destroy uuid=%s" % (snap2uuid))

        # The test passes if the coalesce successfully completes and the contents of the VDI match the expected result.
        self.host.waitForCoalesce(self.sruuid)

        # Listing the number of VHDs in the SR after the snapshot delete.
        afterDeleteNumberOfVHDs = self.host.listVHDsInSR(self.sruuid)
        xenrt.TEC().logverbose("[After Snapshot Delete] Number of VHDs in the default SR is %d" %
                                                                            len(afterDeleteNumberOfVHDs))

        # Checking for the number of VHDs in the SR after the snapshot delete.
        if len(beforeDeleteNumberOfVHDs) != len(afterDeleteNumberOfVHDs) + 2:
            raise xenrt.XRTError("Error coalescing. Expecting %d VHDs. Found %d" %
                                            (len(beforeDeleteNumberOfVHDs)-2, len(afterDeleteNumberOfVHDs)))

class TC19049(xenrt.TestCase):
    """The /var/lock/sm filling up with 32k subdirectories causes master host issues (HFX-651)"""

    NO_OF_DISKS = 10 #NO_OF_DISKS = 31998
    EXTRA_OF_DISKS = 5
    DISK_SIZE = 104857600 # 100MB Disk

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Get the number of locks in /var/lock/sm
        lockCountInitial = int(self.host.execdom0("cd /var/lock/sm && echo */ | wc | awk '{ print $2; }'").strip())
        xenrt.TEC().logverbose("Number of locks before creating the guest: %d" % lockCountInitial)

        # Create basic guest.
        self.guest = self.host.createBasicGuest(distro='centos54')

        lockCountWithGuest = int(self.host.execdom0("cd /var/lock/sm && echo */ | wc | awk '{ print $2; }'").strip())
        xenrt.TEC().logverbose("Number of locks after creating the guest: %d" % lockCountWithGuest)

        self.disks = []
        # Create a number of disks and attach it to the guest.
        for i in range(self.NO_OF_DISKS):
            diskDevice = self.guest.createDisk(sizebytes=self.DISK_SIZE)
            self.disks.append(diskDevice)

        lockCountWithDisks = int(self.host.execdom0("cd /var/lock/sm && echo */ | wc | awk '{ print $2; }'").strip())
        xenrt.TEC().logverbose("Number of locks in /var/lock/sm after creating %d disks are %d" % 
                                                                                        (self.NO_OF_DISKS, lockCountWithDisks))

        if (lockCountWithDisks != lockCountWithGuest+self.NO_OF_DISKS):
            raise xenrt.XRTError("Expecting %d locks. Found only %d" %
                                    (lockCountWithGuest+self.NO_OF_DISKS, lockCountWithDisks))

    def run(self, arglist=None):

        # Get the current number of locks in /var/lock/sm
        lockCountBeforeDiskRemove = int(self.host.execdom0("cd /var/lock/sm && echo */ | wc | awk '{ print $2; }'").strip())
        xenrt.TEC().logverbose("Number of locks in /var/lock/sm before destroying the disk are %d" %
                                                                                        lockCountBeforeDiskRemove)

        # Now delete one disk from the guest to release one lock in /var/lock/sm
        xenrt.TEC().logverbose("Remvoing a disk from the guest.")
        diskDeviceRemove = self.disks.pop() # remove the last disk added.
        self.guest.unplugDisk(diskDeviceRemove)
        self.guest.removeDisk(diskDeviceRemove)

        # VHD Chaining - coalesce takes a while.
        xenrt.sleep(30)

        # Check whether the lock is released
        lockCountAfterDiskRemove = int(self.host.execdom0("cd /var/lock/sm && echo */ | wc | awk '{ print $2; }'").strip())
        xenrt.TEC().logverbose("Number of locks in /var/lock/sm after destroying the disk are %d" %
                                                                                        lockCountAfterDiskRemove)

        if (lockCountAfterDiskRemove != lockCountBeforeDiskRemove-1):
            raise xenrt.XRTError("Expecting %d locks. Found only %d" %
                                                            (lockCountBeforeDiskRemove-1, lockCountAfterDiskRemove))

        # Add some more extra disks.
        xenrt.TEC().logverbose("Adding %d more extra disks." % self.EXTRA_OF_DISKS)
        for i in range(self.EXTRA_OF_DISKS):
            diskDevice = self.guest.createDisk(sizebytes=self.DISK_SIZE)
            self.disks.append(diskDevice)

        # Get the current number of locks in /var/lock/sm
        lockCountAfterExtraDiskAdd = int(self.host.execdom0("cd /var/lock/sm && echo */ | wc | awk '{ print $2; }'").strip())
        xenrt.TEC().logverbose("Number of locks in /var/lock/sm before after adding more disks are %d" %
                                                                                        lockCountAfterExtraDiskAdd)

        if (lockCountAfterExtraDiskAdd != lockCountAfterDiskRemove+self.EXTRA_OF_DISKS):
            raise xenrt.XRTError("Expecting %d locks. Found only %d" %
                                            (lockCountAfterDiskRemove+self.EXTRA_OF_DISKS, lockCountAfterExtraDiskAdd))

        # Now delete all extra disks from the guest to release one lock in /var/lock/sm
        xenrt.TEC().logverbose("Now removing %d more extra disks." % self.EXTRA_OF_DISKS)
        for i in range(self.EXTRA_OF_DISKS):
            diskDeviceRemove = self.disks.pop() # remove the last disk added.
            self.guest.unplugDisk(diskDeviceRemove)
            self.guest.removeDisk(diskDeviceRemove)

        # Again VHD Chaining - coalesce takes a while.
        xenrt.sleep(30 * self.EXTRA_OF_DISKS)

        # Get the current number of locks in /var/lock/sm
        lockCountAfterExtraDiskRemove = int(self.host.execdom0("cd /var/lock/sm && echo */ | wc | awk '{ print $2; }'").strip())
        xenrt.TEC().logverbose("Number of locks in /var/lock/sm before after adding more disks are %d" %
                                                                                        lockCountAfterExtraDiskRemove)

        if (lockCountAfterExtraDiskRemove != lockCountAfterExtraDiskAdd-self.EXTRA_OF_DISKS):
            raise xenrt.XRTError("Expecting %d locks. Found only %d" %
                                            (lockCountAfterExtraDiskAdd-self.EXTRA_OF_DISKS, lockCountAfterExtraDiskRemove))

class TC19052(xenrt.TestCase):
    """Verify the value of VBD_WSECT in xentop command from going too big (HFX-741)"""

    MAX_INT = 2147483647

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createBasicGuest(distro='centos54', memory=4096, disksize=200 * 1024)

    def run(self, arglist=None):
        domainID = self.guest.getDomid()
        virtualDeviceID = int(self.host.execdom0('xenstore-list /local/domain/%d/device/vbd' % domainID))

        # Script to write some datsa to the attached disk.
        writeScript = """#!/bin/bash
# to fully allocate the disk.
dd if=/dev/zero of=/root/delete_me bs=1GB count=1000
touch /root/write_done.dat"""
        self.guest.execguest("echo '%s' > /root/script.sh; exit 0" % writeScript)
        self.guest.execguest("chmod a+x /root/script.sh; exit 0")

        attempt = 1
        while True:
            self.guest.execguest("/root/script.sh < /dev/null > /root/script.log 2>&1 &")
            # Wait until the script is executed before before deleting the file.
            for i in range(50):
                if self.guest.execguest("test -e /root/write_done.dat", retval="code", level=xenrt.RC_OK) == 0:
                    break
                xenrt.sleep(15)
            self.guest.execguest("rm -rf /root/delete_me && rm -rf /root/write_done.dat && rm -rf /root/script.log; exit 0")

            wr_sect = int(self.host.execdom0('cat /sys/bus/xen-backend/devices/vbd-%d-%d/statistics/wr_sect' % 
                                                                                        (domainID, virtualDeviceID)))
            xenrt.TEC().logverbose("Attempt: %d Value of wr_sect from sysfs backend: %d" % (attempt, wr_sect))

            # Check xentop tool displays the VBD_WSECT correctly.
            xenrt.sleep(15) # some time to settle
            xentopData = self.host.getXentopData()
            if xentopData.has_key(self.guest.getName()):
                vbd_wsect = xentopData[self.guest.getName()]['VBD_WSECT'] # VBD write sector
            else:
                raise xenrt.XRTError("No xentop information found for the domain: %s " % self.guest.getName())

            #if wr_sect != vbd_wsect:
            #    raise xenrt.XRTError("The value of VBD_WSECT in xentop command and backend sysfs does not match.")

            if wr_sect < 0: # issue is seen here.
                xenrt.TEC().logverbose("The value of VBD_WSECT as seen in xentop command is %s" % vbd_wsect)
                raise xenrt.XRTError("The value of VBD_WSECT in xentop command is too big.")
            elif wr_sect > self.MAX_INT: # if the issue is fixed
                xenrt.TEC().logverbose("The value of VBD_WSECT as seen in xentop command is %s" % vbd_wsect)
                break # break and check if the value is displayed correctly in xentop command.
            attempt = attempt + 1

class GCCheckOnDisabledHost(xenrt.TestCase):
    """TC-20914: Verify GC cleans up vhd parent node when one of the hosts are in maintenance mode (HFX-996)"""
    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.master = self.getHost("RESOURCE_HOST_0")
        self.slave = self.getHost("RESOURCE_HOST_1")
        self.guest = self.master.createGenericLinuxGuest()

    def run(self, arglist = None):
        self.localSr = self.master.getLocalSR()
        self.vdi = self.master.createVDI(xenrt.GIGA, self.localSr)
        self.guest.createDisk(vdiuuid=self.vdi)
        self.snap1uuid = self.master.snapshotVDI(self.vdi)
        self.vhdParent1 = self.master.vhdQueryParent(self.snap1uuid)
        #Verify snapshot delete after slave enters maintenance mode. 
        self.slave.disable()
        self.master.destroyVDI(self.snap1uuid)
        time.sleep(10)
        if self.master.vhdExists(self.vhdParent1, self.localSr):
            raise xenrt.XRTFailure("VHD Parent persists post deleting the snapshot after slave is disabled. GC is not cleaning up.")
        xenrt.TEC().logverbose("GC is cleaning up as expected when slave is disabled.")
        
        #Same process for the case of master's
        self.slave.enable()
        self.snap2uuid = self.slave.snapshotVDI(self.vdi)
        self.vhdParent2 = self.slave.vhdQueryParent(self.snap2uuid)
        #Verify snapshot delete after master enters maintenance mode. 
        self.master.disable()
        self.slave.destroyVDI(self.snap2uuid)
        time.sleep(10)
        if self.slave.vhdExists(self.vhdParent2, self.localSr):
            raise xenrt.XRTFailure("VHD Parent persists post deleting the snapshot after master is disabled. GC is not cleaning up.")
        self.slave.waitForCoalesce(self.localSr)
        xenrt.TEC().logverbose("GC is cleaning up as expected when master is disabled.")
        
        
class TCVDICopyDeltas(xenrt.TestCase):
    """Verify vdi-copy options to only copy deltas"""
    
    COPY_INTO_EMPTY_VDI=False
    
    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.cli = self.host.getCLIInstance()
        self.guest = self.host.createGenericLinuxGuest()
        
        server, path = xenrt.ExternalNFSShare().getMount().split(":")
        self.sr = xenrt.lib.xenserver.NFSStorageRepository(self.host, "vdicopynfs")
        if not xenrt.TEC().lookup("NFSSR_WITH_NOSUBDIR", None):
            self.sr.create(server, path)
        else:
            self.sr.create(server, path, nosubdir=True) # NFS SR with no sub directory

        # Create a disk on the guest which can be backed up
        
        vbdUUID = self.guest.createDisk(sizebytes = xenrt.GIGA, returnVBD=True, userdevice=1, sruuid=self.sr.uuid)
        self.vbd = xenrt.lib.xenserver.VBD(self.cli, vbdUUID)
        self.vdi = self.vbd.VDI
        self.device = self.vbd.device
        self.guest.execguest("mkfs.ext3 /dev/%s" % self.device)
        self.guest.execguest("mkdir -p /test")

    def diskMd5Sum(self, device):
        return self.guest.execguest("md5sum /dev/%s" % device).split()[0]

    def vdiMd5Sum(self, vdi):
        vbdUUID = self.cli.execute("vbd-create device=2 vdi-uuid=%s vm-uuid=%s" % (vdi.uuid, self.guest.getUUID())).strip()
        vbd =  xenrt.lib.xenserver.VBD(self.cli, vbdUUID)
        vbd.plug()
        xenrt.sleep(5)

        md5 = self.diskMd5Sum(vbd.device)
        
        vbd.unPlug()
        vbd.destroy()
        return md5
    
    def vdiCopy(self, vdi, baseVdi=None, intoVdi=None):
        params = ""
        if intoVdi:
            params = "into-vdi-uuid=%s" % intoVdi.uuid
        else:
            if self.COPY_INTO_EMPTY_VDI:
                emptyVdiUuid = self.cli.execute("vdi-create sr-uuid=%s name-label=%s type=user virtual-size=%s" % (
                            self.sr.uuid, vdi.name, vdi.size)).strip()
                params = "into-vdi-uuid=%s" % emptyVdiUuid
            else:
                params = "sr-uuid=%s " % self.sr.uuid
        
        if baseVdi:
            params += " base-vdi-uuid=%s" % baseVdi.uuid
            
        return vdi.copy(params)

    def vhdSize(self, vdi):
        return int(self.host.execdom0("ls -l /var/run/sr-mount/%s/%s.vhd | awk '{print $5}'" % (self.sr.uuid, vdi.uuid)).strip())

    def run(self, arglist):
        snapshots = []
        originalMD5s = []
        # 3 iterations
        # - Mount the disk
        # - Write some random data to the VDI
        # - Unmount the disk (prevent any more writes)
        # - md5sum the disk and remember it for later comparison
        # - Take a snapshot

        for i in xrange(3):
            self.guest.execguest("mount /dev/%s /test" % self.device)
            self.guest.execguest("dd if=/dev/urandom bs=1M count=20 of=/test/data%u" % i)
            self.guest.execguest("umount /test")
            originalMD5s.append(self.diskMd5Sum(self.device))
            snapshots.append(self.vdi.snapshot())
        
        vdiBaseCopied = self.vdiCopy(snapshots[0])
        # Check the copied MD5sum matches the main VDI.
        if self.vdiMd5Sum(vdiBaseCopied) != originalMD5s[0]:
            raise xenrt.XRTFailure("Disk MD5SUM didn't match after first copy")
        
        # Copy the differences between the base and snapshots[1] to a new VDI
        vdiDeltaCopied1 = self.vdiCopy(snapshots[1], baseVdi = snapshots[0])
        # Also do a full copy of the snapshots[1] to check that there is a difference between delta copy and full copy
        vdiFullCopied1 = self.vdiCopy(snapshots[1])
        
        # And do the same for snapshots[2] using snapshots[1] as the base disk (to check it works when there isn't a base VHD)

        # Copy the differences between the snapshots[1] and snapshots[2] to a new VDI
        vdiDeltaCopied2 = self.vdiCopy(snapshots[2], baseVdi = snapshots[1])
        # Also do a full copy of the snapshots[1] to check that there is a difference between delta copy and full copy
        vdiFullCopied2 = self.vdiCopy(snapshots[2])
        
        # As vdiDeltaCopied only has the deltas, whereas vdiCopied3 is a full copy, vdiCopied2 should be smaller
        # We'll set a threshold of 90%, which is generous, but should verify it's doing the right thing
       
        sizeFull1 = self.vhdSize(vdiFullCopied1)
        sizeDelta1 = self.vhdSize(vdiDeltaCopied1)
        sizeFull2 = self.vhdSize(vdiFullCopied2)
        sizeDelta2 = self.vhdSize(vdiDeltaCopied2)

        # Check that the size of the diff is < 90% the size of the full copy

        if sizeDelta1 > (sizeFull1 * 0.9):
            raise xenrt.XRTFailure("Size of delta of snapshots[1] copy > 90% size of full copy")

        if sizeDelta2 > (sizeFull2 * 0.9):
            raise xenrt.XRTFailure("Size of delta of snapshots[2] copy > 90% size of full copy")


        # To verify the integrity of the delta copy, we need to coalesce it with the base
        # Copy the base copy into a new VDI
        
        vdiCoalescedFromCopies = self.vdiCopy(vdiBaseCopied)
        
        # Then coalesce the first delta into this VDI        
        self.vdiCopy(vdiDeltaCopied1, intoVdi = vdiCoalescedFromCopies)
        
        # Check the copied MD5sum matches the main VDI.
        if self.vdiMd5Sum(vdiCoalescedFromCopies) != originalMD5s[1]:
            raise xenrt.XRTFailure("Disk MD5SUM didn't match after delta copy and coalesce")

        # Then coalesce the second delta into this VDI        
        self.vdiCopy(vdiDeltaCopied2, intoVdi = vdiCoalescedFromCopies)
        
        # Check the copied MD5sum matches the main VDI.
        if self.vdiMd5Sum(vdiCoalescedFromCopies) != originalMD5s[2]:
            raise xenrt.XRTFailure("Disk MD5SUM didn't match after delta copy and coalesce")


        # Test coalescing the snapshots onto a single VDI
        vdiCoalescedFromSnaps = self.vdiCopy(snapshots[0])
        self.vdiCopy(snapshots[1], intoVdi = vdiCoalescedFromSnaps, baseVdi = snapshots[0])
        
        if self.vdiMd5Sum(vdiCoalescedFromSnaps) != originalMD5s[1]:
            raise xenrt.XRTFailure("Disk MD5SUM didn't match after snapshot copy coalesce")

        # And also coalesce snapshots[2]

        self.vdiCopy(snapshots[2], intoVdi = vdiCoalescedFromSnaps, baseVdi = snapshots[1])
        
        if self.vdiMd5Sum(vdiCoalescedFromSnaps) != originalMD5s[2]:
            raise xenrt.XRTFailure("Disk MD5SUM didn't match after snapshot copy coalesce")
        

    def postRun(self):
        self.guest.uninstall()
        self.sr.remove()

class TC20915(TCVDICopyDeltas):
    """Test vdi-copy options for copying and coalescing deltas (vdi-copy creates new VDIs)"""
    
class TC20916(TCVDICopyDeltas):
    """Test vdi-copy options for copying and coalescing deltas (vdi-copy into existing VDIs)"""
    COPY_INTO_EMPTY_VDI=True

class TCCrossHostVmCopy(xenrt.TestCase):
    """ Base class for cross host, cross SR, VM operations test for HVM and PV Guests"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.srUUIDsMaster = []
        self.srUUIDsSlave = []

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        self.master = self.pool.master
        self.slave = self.pool.slaves.values()[0]
        
        self.localsr1 = self.master.getSRs(type="lvm")
        self.localsr2 = self.slave.getSRs(type="lvm")
        self.nfssr = self.master.getSRs(type="nfs")
        self.iscsisr = self.master.getSRs(type="lvmoiscsi")
        
        self.guests = [ self.master.getGuest(g) for g in self.master.listGuests()]

        for sr in [ self.localsr1, self.nfssr, self.iscsisr ]:
            if sr:
                self.srUUIDsMaster.append(sr[0])

        for sr in [ self.localsr2, self.nfssr, self.iscsisr ]:
            if sr:
                self.srUUIDsSlave.append(sr[0])

    def testVmCopyOnSr(self, guest, sr):
        step("Single host: Copying guest VM from local SR of master to SR %s of master as guestcopy." % sr)
        try:
            guestcopy = guest.copyVM(sruuid = sr)
        except:
            raise xenrt.XRTFailure("Single host copying of guest %s failed from local SR to SR %s." % (guest.name, sr))
        step("Cross host: Copying guestcopy from master to slave on All slave SRs and checking copied guests on slave.")
        for sr2 in self.srUUIDsSlave:
            try:
                guestcopycopy = guestcopy.copyVM(sruuid = sr2)
            except:
                raise xenrt.XRTFailure("Cross host copying of guest %s failed from SR %s to SR %s." % (guest.name, sr ,sr2))
            guestcopycopy.host = self.slave
            guestcopycopy.start(specifyOn=True)
            guestcopycopy.check()
            guestcopycopy.uninstall()
        step("Checking guests which were copied on master host")
        guestcopy.host = self.master
        guestcopy.start(specifyOn=True)
        guestcopy.check()
        guestcopy.uninstall()

    def run(self, arglist):
        for guest in self.guests:
            guest.shutdown()
            for sr in self.srUUIDsMaster:
                self.runSubcase("testVmCopyOnSr", (guest, sr), guest.name, sr)
            guest.start()

class SRIntroduceBase(xenrt.TestCase):
    """Base class for introducing a previously forgotten SR"""

    SR_TYPE = None
    NFSSR_WITH_NOSUBDIR = False

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        server, path = xenrt.ExternalNFSShare().getMount().split(":")
        
        # Create the SR on the host
        if self.SR_TYPE == "nfs":
            self.sr = xenrt.lib.xenserver.NFSStorageRepository(self.host, "nfssr-with-nosubdir")
            if not self.NFSSR_WITH_NOSUBDIR:
                self.sr.create(server, path)
            else:
                self.sr.create(server, path, nosubdir=True) # NFS SR with no sub directory sanity test
                
        elif self.SR_TYPE == "file":
            self.sr = xenrt.lib.xenserver.FileStorageRepositoryNFS(self.host, "filesr")
            self.sr.create(server, path)
        else:
            raise xenrt.XRTFailure("SR Type not defined")

        self.vdiuuid = self.host.getCLIInstance().execute("vdi-create", \
                    "sr-uuid=%s virtual-size=1024 name-label=XenRTTest type=user" % self.sr.uuid, strip=True)
        self.originalSize = self.host.genParamGet("vdi", self.vdiuuid, "virtual-size")
        self.sr.forget()
    
    def run(self, arglist):
        if not self.NFSSR_WITH_NOSUBDIR:
            self.sr.introduce()
        else:
            self.sr.introduce(nosubdir=True) # NFS SR with no sub directory sanity test

        self.sr.scan()
        # Check the VDI is present
        vdis = self.host.minimalList("vdi-list", args="sr-uuid=%s" % self.sr.uuid)
        if len(vdis) != 1:
            raise xenrt.XRTFailure("Number of VDIs not as expected after re-introduce. Expected 1, got %d" % len(vdis))
        if vdis[0] != self.vdiuuid:
            raise xenrt.XRTFailure("VDI UUID was not as expected after re-introducing SR")
        newSize = self.host.genParamGet("vdi", self.vdiuuid, "virtual-size")
        if newSize != self.originalSize:
            raise xenrt.XRTFailure("VDI virtual-size was not as expected - expected %d, got %d" % \
                                (self.originalSize, newSize))

class TC20947(SRIntroduceBase):
    """Introduce a previously forgotten file SR"""

    SR_TYPE = "file"

class TC20979(SRIntroduceBase):
    """Introduce a previously forgotten nfs SR with no sub directory"""
    
    SR_TYPE = "nfs"
    NFSSR_WITH_NOSUBDIR = True
    
class TC21718(xenrt.TestCase):
    """ Verify creating PBD with SRmaster key set to true throws exception"""
    
    SR_TYPE = "nfs"
    
    def prepare(self, arglist):
        # Get a host to use
        self.host = self.getDefaultHost()
        self.sruuid = self.host.getSRs(type=self.SR_TYPE)
        
    def run(self, arglist):
        args = []
        args.append("host-uuid=%s" % (self.host.getMyHostUUID()))
        args.append("sr-uuid=%s" % self.sruuid[0])
        pbd = self.host.minimalList("pbd-list", args=string.join(args))[0]
        
        cli = self.host.getCLIInstance()
        cli.execute("pbd-unplug", "uuid=%s" % (pbd))
        cli.execute("pbd-destroy", "uuid=%s" % (pbd))
        
        try:
            args = []
            args.append("host-uuid=%s" % (self.host.getMyHostUUID()))
            args.append("sr-uuid=%s" % (self.sruuid[0]))
            args.append("device-config:SRmaster=true")
            pbd = cli.execute("pbd-create", string.join(args)).strip()
            
        except Exception, e:
        
            if e.data and re.search(r"This key is for internal use only",e.data):
                xenrt.TEC().logverbose("Setting SRmaster key in pbd device config failed with expected message")
                return
        raise xenrt.XRTFailure("SRmaster key in PBD device config can be set while creating PBD")

class TCPbdDuplicateSecret(xenrt.TestCase):
    """Duplicate device-config:password_secret should not be created.Regression test for SCTX-1486"""
    # Jira TC-21719

    def prepare(self, arglist=None):
        self.srs = []
        self.srsToRemove = []
        self.host = self.getDefaultHost()
        self.host1 = self.getHost("RESOURCE_HOST_1")
        self.pool = self.getDefaultPool()

        # Create a Windows VM to be the CIFS server.
        self.guest = xenrt.TEC().registry.guestGet("CIFSSERVER")
        if not self.guest:
            self.guest = self.host.createGenericWindowsGuest()
            self.uninstallOnCleanup(self.guest)
        
        # Enable file and printer sharing on the guest.
        self.guest.xmlrpcExec("netsh firewall set service type=fileandprint "
                              "mode=enable profile=all")

        self.exports = []
        # Create a user account.
        user = "Administrator"
        password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])

        # Share a directory.
        sharedir = self.guest.xmlrpcTempDir()
        sharename = "XENRTSHARE"
        self.guest.xmlrpcExec("net share %s=%s /GRANT:%s,FULL" %
                                    (sharename, sharedir, user))

        self.exports.append((sharename, user, password))

        self.client = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.client)
        self.secrets = []

    def run(self, arglist=None):
        # Attach the share as a CIFS ISO to the pool.
        sharename, user, password = self.exports[0]
        sr = xenrt.lib.xenserver.CIFSISOStorageRepository(self.host,"cifstest")

        self.srs.append(sr)

        self.srsToRemove.append(sr)

        # Create a secret
        secret_uuid = self.host.createSecret(password)
        self.secrets.append(secret_uuid)

        sr.create(self.guest.getIP(),
                    sharename,
                    "iso",
                    "iso",
                    username=user,
                    password=secret_uuid,
                    use_secret=True,
                    shared=False)
        cli=self.host.getCLIInstance()
        cli.execute("sr-param-set","uuid=%s shared=true" % self.srs[0].uuid)

        #create a pbd for slave host with same password secret as master
        pbd1=self.srs[0].getPBDs().keys()[0]

        master_pbd_dc = self.host.genParamsGet("pbd",pbd1,"device-config")
        master_pbd_username = master_pbd_dc['username']
        master_pbd_cifspassword_secret = master_pbd_dc['cifspassword_secret']
        master_pbd_location = master_pbd_dc['location']
        master_pbd_type = master_pbd_dc['type']

        self.dconf = {"username": master_pbd_username , "cifspassword_secret": master_pbd_cifspassword_secret , "location":master_pbd_location, "type": master_pbd_type}

        args = []
        args.append("host-uuid=%s" % (self.host1.getMyHostUUID()))
        args.append("sr-uuid=%s" % (self.srs[0].uuid))
        args.extend(["device-config:%s=\"%s\"" % (x, y) for x,y in self.dconf.items()])
        
        pbd2 = cli.execute("pbd-create", string.join(args)).strip()

        cli.execute("pbd-plug uuid=%s" % pbd2)

        #check if password secret of both pbds are different.

        passwordSecret1=self.host.genParamsGet("pbd",pbd1,"device-config")['cifspassword_secret']
        passwordSecret2=self.host.genParamsGet("pbd",pbd2,"device-config")['cifspassword_secret']

        if passwordSecret1 == passwordSecret2:	
            raise xenrt.XRTFailure('Unexpected Output: Created 2 pbds with same password secret')	
        else:
            xenrt.TEC().logverbose("Expected output: New pbd has different password secret")

    def postRun(self):
        for sr in self.srsToRemove:
            try:
                sr.remove()
            except:
                pass

class TCVdiCorruption(xenrt.TestCase):
    """TC to verify VDI corruption on writing data to a 2TB VDI (SCTX-1406)"""
    #Jira TC-21641
    
    SRTYPE = "lvm"
    SIZE = 2048 * xenrt.GIGA

    def prepare(self, arglist):
        self.vdi = None
        self.vbd = None
        self.host = self.getDefaultHost()
        g=self.host.listGuests(running=True)
        self.guest=self.host.getGuest(g[0])
        self.cli = self.host.getCLIInstance()
        srs = self.host.getSRs(type=self.SRTYPE)
        if not srs:
            raise xenrt.XRTError("No %s SR found on host." % (self.SRTYPE))
        self.sr = srs[0]

    def run(self, arglist):
        step("Create vdi and plug VBD to guest")
        self.vdi = self.host.createVDI(self.SIZE, self.sr)
        device = self.guest.createDisk(vdiuuid=self.vdi,returnDevice=True)
        xenrt.TEC().logverbose("Plugged VBD %s" %(device))
        self.vbd = self.guest.getDiskVBDUUID(device)
        xenrt.TEC().logverbose("Plugged VBD %s" %(self.vbd))

        step("Upgrade host")
        self.host = self.host.upgrade()
        self.host.applyRequiredPatches()
        
        step("Start VM")
        self.guest.start()
        xenrt.TEC().logverbose("Formatting VDI within VM.")
        time.sleep(10)
        self.guest.execguest("mkfs.ext3 /dev/%s" % (device))
        self.guest.execguest("mkdir /mnt/vdi1")
        self.guest.execguest("mount /dev/%s /mnt/vdi1" % (device))
        try:
            outfile = self.guest.execguest("dd if=/dev/zero of=/mnt/vdi1/file1 bs=512 count=4294967400 conv=notrunc", timeout=43200)
        except Exception, e:
            xenrt.TEC().logverbose("Exception raised: %s" % (str(e)))
            availSpace = self.guest.execguest("df -h /dev/%s | tail -n 1 | awk '{print $4}'" % (device)).strip()
            if "Input/output error" in str(e.data):
                if availSpace == "0":
                    xenrt.TEC().logverbose("Expected output: Disk is full and dd command exited with an error")
                else:
                    raise xenrt.XRTError("Input/Error thrown before disk is full. available space=%s" % (availSpace))
            elif "SSH timed out" in str(e) and availSpace == "0":
                #Workaround due to CA-122162- dd command doesn't crash when 2TB VDI is full
                #raise xenrt.XRTFailure("dd command didn't return after disk is full. available space=%s" % (availSpace))
                #check if vdi is corrupted
                filename = "/dev/VG_XenStorage-%s/VHD-%s" % (self.sr,self.vdi)
                try:
                    self.host.execdom0("vhd-util check -n %s" % filename)
                except Exception, e:
                    if "error calculating end of metadata" in str(e.data):
                        raise xenrt.XRTFailure("VDI corruption on writing 2TB data")
            else: 
                raise xenrt.XRTFailure("Unexpected error occured: %s" % (str(e)))
        else:
            availSpace = self.guest.execguest("df -h /dev/%s | tail -n 1 | awk '{print $4}'" % (device)).strip()
            if availSpace <> "0":
                raise xenrt.XRTFailure("Unexpected output. Disk is not full and dd command exited without any error.available space=%s" % (availSpace))
    
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

class CifsSRGuestLifeCycle(xenrt.TestCase):
    """Guests life cycle operations on CIFS SR"""

    def guestsLifeCycle(self, guests):

        xenrt.TEC().logverbose("Guests Life Cycle Operations on CIFS SR ...")

        for guest in guests:

            # Make sure the guest is up.
            if guest.getState() == "DOWN":
                xenrt.TEC().logverbose("Starting guest before commencing lifecycle ops.")
                guest.start()

            guest.shutdown()
            guest.start()
            guest.reboot()
            guest.suspend()
            guest.resume()
            guest.shutdown()

    def run(self, arglist):
        pass

class TC26472(CifsSRGuestLifeCycle):
    """Guests life cycle operations on CIFS SR using SMB share provided by a Windows guest"""

    def run(self, arglist):

        host = self.getDefaultHost()
        srs = host.minimalList("sr-list", args="name-label=\"CIFS-SR\"")
        if not srs:
            raise xenrt.XRTFailure("Unable to find a CIFS SR configured on host %s" % host)

        # Exclude xenrt-smb guest which serves the smb share.
        guests = [host.getGuest(g) for g in host.listGuests() if not g.startswith("xenrt-smb")]

        self.guestsLifeCycle(guests) # Carry out guests life cycle operations.

class TC26950(CifsSRGuestLifeCycle):
    """Multiple CIFS SRs using multiple authentication provided by NetApp SMB Share"""

    def run(self, arglist):

        host = self.getDefaultHost() # The host has already 2 CIFS SRs created using
                                     # different authentication on QA NetApp filer.
                                     # One SR on a SMB share provided by a windows guest

        # Exclude xenrt-smb guest which serves the smb share.
        guests = [host.getGuest(g) for g in host.listGuests() if not g.startswith("xenrt-smb")]

        self.guestsLifeCycle(guests) # Carry out guests life cycle operations.

class TC26976(xenrt.TestCase):
    """Verify a minimum of 256 CIFS SRs can be created in XenServer environment"""

    LIMIT = 256

    def run(self, arglist=[]):
        self.host = self.getDefaultHost()

        # Create CIFS SRs on host.
        counter = 0
        timeNow = xenrt.util.timenow()
        smbShare = xenrt.ExternalSMBShare(version=3) # This will obtain the SMB Share from NetApp filer.

        maximumReached = True
        count = 0
        self.cifsSRs = []
        while maximumReached:
            try:
                cifsSRName = "cifsSR-%d" % count 
                xenrt.TEC().logverbose("Creating %d CIFS SR: %s" % (count, cifsSRName))
                cifsSR = xenrt.productLib(host=self.host).SMBStorageRepository(self.host, cifsSRName)
                cifsSR.create(smbShare)
                self.cifsSRs.append(cifsSR)
                count = count + 1
                if count == self.LIMIT: break
            except xenrt.XRTFailure, e:
                maximumReached = False
                if count > 0: # one or more SRs are created.
                    xenrt.TEC().logverbose("The number of CIFS SRs created on host %s are %s" %
                                                                                (self.host, count))
                else:
                    raise xenrt.XRTError(e.reason)

        xenrt.TEC().logverbose("Time taken to create %d CIFS SRs on host %s is %s seconds." % 
                                        (self.LIMIT, self.host, (xenrt.util.timenow() - timeNow)))

    def postRun(self, arglist=[]):

        # Destroy the CIFS SRs.
        timeNow = xenrt.util.timenow()
        for cifsSR in self.cifsSRs:
            self.host.destroySR(cifsSR.uuid)
        xenrt.TEC().logverbose("Time taken to destroy %d CIFS SRs on host is %s seconds." %
                                            (len(self.cifsSRs), (xenrt.util.timenow() - timeNow)))

class TC26974(xenrt.TestCase):
    """Verify can create CIFS SR after upgrading the host."""

    def prepare(self, arglist):

        self.host = self.getDefaultHost()

    def run(self, arglist):

        self.host = self.host.upgrade()
        #Applying license to the host
        self.host.license(edition="enterprise-per-socket")
        share = xenrt.VMSMBShare()
        sr = xenrt.productLib(host=self.host).SMBStorageRepository(self.host, "CIFS-SR")
        sr.create(share)

class TCCIFSLifecycle(xenrt.TestCase):
    """SR Lifecycle operations."""

    def prepare(self, arglist):

        self.args = self.parseArgsKeyValue(arglist)

        self.host = self.getDefaultHost()
        srtype = "cifs"

        xsr = next((s for s in self.host.xapiObject.localSRs if s.srType == srtype), None)
        self.sr = xenrt.lib.xenserver.SMBStorageRepository.fromExistingSR(self.host, xsr.uuid)

    def run(self, arglist):
        noOfVdis = int(self.args["numberofvdis"])
        sizeInBytes = int(self.args["size"])

        # Create some VDIs
        actualVdis = [self.host.createVDI(sizeInBytes, sruuid=self.sr.uuid, name="VDI_%s" % i)for i in range(noOfVdis)]

        # Forget SR
        self.sr.forget()

        # Introduce SR
        self.sr.introduce()
        xenrt.sleep(100)
        
        self.sr.scan()
        VDIs_present = set(self.sr.listVDIs())
        # Get a list of any VDIs that are now missing
        VDIs_missing = filter(lambda vdi: vdi not in VDIs_present, actualVdis)

        xenrt.TEC().logverbose("VDIs missing after SR introduce: %s" % (",".join(VDIs_missing)))
            
        if len(VDIs_missing) > 0:
            raise xenrt.XRTFailure("VDIs are missing after SR introduce")

        self.sr.check()

        # Destroy SR.
        self.sr.remove()

class TCDuplicateVdiName(xenrt.TestCase):
    """Test that VDIs with identical names can be created and don't change on rescan"""

    def run(self, arglist):
        host = self.getDefaultHost()
        sr = host.getSRs(self.tcsku)[0]
        # Create 2 VDIs with the name "duplicate"
        vdis = []
        vdis.append(host.createVDI("1GiB", sr, name="duplicate"))
        vdis.append(host.createVDI("1GiB", sr, name="duplicate"))
        # TODO write some random data to each VDI here, and check for unique MD5sums
        locations = {}
        names = {}
        # Check the name-label is "duplicate"
        for v in vdis:
            if host.genParamGet("vdi", v, "name-label") != "duplicate":
                raise xenrt.XRTFailure("name-label on VDI is incorrect before rescan")
            locations[v] = host.genParamGet("vdi", v, "location")
        # Check the location is unique 
        if locations[vdis[0]] == locations[vdis[1]]:
            raise xenrt.XRTFailure("locations of the 2 VDIs are not unique")
        # Rescan the SR
        host.getCLIInstance().execute("sr-scan", "uuid=%s" % sr)
        # TODO check the MD5sums haven't changed after rescan
        # Verify that the name and location haven't changed after scan
        for v in vdis:
            if host.genParamGet("vdi", v, "location") != locations[v]:
                raise xenrt.XRTFailure("VDI location changed after scan")
            if host.genParamGet("vdi", v, "name-label") != "duplicate":
                raise xenrt.XRTFailure("VDI name-label changed after scan")
        
        for v in vdis:
            host.destroyVDI(v)

class TCVdiSpaceInName(xenrt.TestCase):
    """Test that VDIs with spaces in the name can be used"""

    def run(self, arglist):
        host = self.getDefaultHost()
        sr = host.getSRs(self.tcsku)[0]
        vdi = host.createVDI("1MiB", sr, name="VDI With Space")

        if host.genParamGet("vdi", vdi, "name-label") != "VDI With Space":
            raise xenrt.XRTFailure("VDI name-label is incorrect")
        
        # Rescan the SR
        host.getCLIInstance().execute("sr-scan", "uuid=%s" % sr)
        
        if host.genParamGet("vdi", vdi, "name-label") != "VDI With Space":
            raise xenrt.XRTFailure("VDI name-label is incorrect after scan")

        host.getVdiMD5Sum(vdi)

        host.destroyVDI(vdi)

class TCAllPBDsPlugged(xenrt.TestCase):
    def run(self, arglist):
        for host in self.getDefaultPool().getHosts():
            for pbd in host.minimalList("pbd-list"):
                if host.genParamGet("pbd", pbd, "currently-attached") != "true":
                    raise xenrt.XRTFailure("Not all PBDs were attached after pool join")

class TCSRConfigConsistency(xenrt.TestCase):
    """Check PBD has same sm-config after plug/unplug"""

    SR_TYPE = "lvmoiscsi"

    def run(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        host = self.getDefaultHost()
        sr = host.getSRs(args.get("srtype", self.SR_TYPE))[0]

        step("Obtain current sm config")
        smBefore = host.genParamsGet("sr", sr, "sm-config")

        step("PBD unplug/plug")
        cli = host.getCLIInstance()
        pbds = host.minimalList("pbd-list", args="sr-uuid=%s" % sr)
        for pbd in pbds:
            cli.execute("pbd-unplug", "uuid=%s" % pbd)
        xenrt.sleep(5)
        for pbd in pbds:
            cli.execute("pbd-plug", "uuid=%s" % pbd)

        step("Compare sm config after unplug/plug")
        smAfter = host.genParamsGet("sr", sr, "sm-config")

        log("sm-config before pbd-unplug: %s" % smBefore)
        log("sm-config after pbd-plug: %s" % smAfter)

        if len(smBefore) != len(smAfter):
            raise xenrt.XRTFailure("sm-configs before and after pbd unplug/plug are different.")

        for key in smBefore:
            if key not in smAfter:
                xenrt.XRTFailure("%s key was in sm-config before pbd plug/unplug")
            if smBefore[key] != smAfter[key]:
                xenrt.XRTFailure("%s key mismatched. before: %s, after: %s" % (key, smBefore[key], smAfter[key]))

class FCOELifecycleBase(xenrt.TestCase):

    SRTYPE = "lvmofcoe"

    def prepare(self, arglist):
        
        self.host = self.getDefaultHost()
        self.srs = self.host.getSRs(type = self.SRTYPE)
        
class TCFCOESRLifecycle(FCOELifecycleBase):
    """FCOE SR Lifecycle operations"""

    def run(self, arglist):

        self.sr = xenrt.lib.xenserver.FCOEStorageRepository.fromExistingSR(self.host, self.srs[0])
        self.vdiuuid = self.host.createVDI(sizebytes=1024, sruuid=self.sr.uuid, name="XenRTTest" )
        originalVdiSize = self.host.genParamGet("vdi", self.vdiuuid, "virtual-size")
        self.sr.forget()
        
        self.sr.introduce()
        self.sr.scan()
       
        vdiList = self.host.minimalList("vdi-list", args="sr-uuid=%s" % self.sr.uuid)
        if len(vdiList) != 1:
            raise xenrt.XRTFailure("Number of VDIs not as expected after re-introduce. Expected 1, got %d" % len(vdiList))
            
        if vdiList[0] != self.vdiuuid:
            raise xenrt.XRTFailure("VDI UUID was not as expected after re-introducing SR")
            
        newVdiSize = self.host.genParamGet("vdi", self.vdiuuid, "virtual-size")
        if newVdiSize != originalVdiSize:
            raise xenrt.XRTFailure("VDI virtual-size was not as expected - expected %d, got %d" % \
                                (originalVdiSize, newVdiSize))

        self.sr.check()
        self.host.destroyVDI(self.vdiuuid)
        
class TCFCOEGuestLifeCycle(FCOELifecycleBase):
    """Guest Lifecycle operations on FCoE SR."""

    def run(self, arglist):

        if not self.srs:
            raise xenrt.XRTFailure("Unable to find a LVMoFCoE SR configured on host %s" % self.host)

        self.guests = [self.host.getGuest(g) for g in self.host.listGuests()]

        for guest in self.guests:
            if self.runSubcase("lifecycle", guest, "VM", "Lifecycle") != \
                    xenrt.RESULT_PASS:
                return
            if self.runSubcase("suspendresume", guest, "VM", "SuspendResume") != \
                    xenrt.RESULT_PASS:
                return
            if self.runSubcase("snapshot", guest, "VM", "Snapshot") != \
                    xenrt.RESULT_PASS:
                return
            if self.runSubcase("clone", guest, "VM", "Clone") != \
                    xenrt.RESULT_PASS:
                return
            if self.runSubcase("uninstall", guest, "VM", "Uninstall") != \
                    xenrt.RESULT_PASS:
                return

    def lifecycle(self, guest):
        # Perform some lifecycle operations
        guest.reboot()
        guest.shutdown()
        guest.start()
        guest.check()

    def suspendresume(self, guest):
        guest.suspend()
        guest.resume()
        guest.check()
        guest.suspend()
        guest.resume()
        guest.check()

    def snapshot(self, guest):
        snapuuid = guest.snapshot()
        guest.getHost().removeTemplate(snapuuid)
        
        checkpointuuid = guest.checkpoint()
        guest.getHost().removeTemplate(checkpointuuid)
        
    def clone(self, guest):
        if guest.getState() == "UP":
            guest.shutdown()

        clone = guest.cloneVM()
        clone.uninstall()

    def uninstall(self, guest):
        guest.uninstall()

class TCFCOEVerifySRProbe(FCOELifecycleBase):
    """Verify FCoE SR Probe operation output has Ethernet information."""

    def run(self, arglist):

        if self.srs:
            self.sr = xenrt.lib.xenserver.FCOEStorageRepository.fromExistingSR(self.host, self.srs[0])
            self.sr.forget()
            
        cli = self.host.getCLIInstance()
        failProbe = False
        
        args = []
        args.append("type=%s" %(self.SRTYPE))
        
        try:
            cli.execute("sr-probe", string.join(args))
            failProbe = True

        except xenrt.XRTFailure, e:

            split = e.data.split("<?",1)
            if len(split) != 2:
                raise xenrt.XRTFailure("Couldn't find XML output from "
                                       "sr-probe command")

            dom = xml.dom.minidom.parseString("<?" + split[1])
            blockDevices = dom.getElementsByTagName("BlockDevice")
            found = False

            for b in blockDevices:
                luns = b.getElementsByTagName("lun")
                if len(luns) == 0:
                    continue
                
                lun = luns[0].childNodes[0].data.strip()
                eths = b.getElementsByTagName("eth")
                
                if len(eths) == 0:
                    raise xenrt.XRTFailure("Couldn't find ethernet for "
                                           "lun %u in XML output" %
                                           (lun))
                eth = eths[0].childNodes[0].data.strip()
                log("Found ethernet information %s for lun %s " %(eth , lun))
                found = True

                if not found:
                    raise xenrt.XRTFailure("Couldn't find lun in XML output")

                if failProbe:
                    raise xenrt.XRTFailure("sr-probe unexpectedly returned "
                                           "successfully when attempting to "
                                           "find Ethernet information for the luns")

class TCFCOEAfterUpgrade(FCOELifecycleBase):
    """Verify FCOE SR after upgrade to Dundee"""

    def prepare(self, arglist=None):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   withisos=True)
        # Upgrade the host
        self.host.upgrade()
    
    def run(self,arglist):
        
        self.fcLun = self.host.lookup("SR_FCHBA", "LUN0")
        self.fcSRScsiid = self.host.lookup(["FC", self.fcLun, "SCSIID"], None)
        self.fcSR = xenrt.lib.xenserver.FCOEStorageRepository(self.host, "FCOESR")
        self.fcSR.create(self.fcSRScsiid)
        self.host.addSR(self.fcSR, default=True)
        
        self.srs = self.host.getSRs(type = self.SRTYPE)
        
        if not self.srs:
            raise xenrt.XRTFailure("FCOE SR Creation failed after host upgrade on %s" % self.host)

class TCFCOEBlacklist(xenrt.TestCase):

    BLACKLIST_FILE = "/etc/sysconfig/fcoe-blacklist"
    
    def prepare(self,arglist=None):
        self.host = self.getDefaultHost()
        fcoesr = self.host.lookup("SR_FC", "yes")
        if fcoesr == "yes":
            fcoesr = "LUN0"
        self.scsiid = self.host.lookup(["FC", fcoesr, "SCSIID"], None)
        self.sr = xenrt.lib.xenserver.FCOEStorageRepository(self.host, "fcoe")
        self.sr.create(self.scsiid,multipathing=True)
        
        
    def isNICFCOECapable(self,pif):
        var = self.host.execdom0("dcbtool gc %s app:0" % pif)
        v = re.search(r'Enable:\s+(\w+)',var)
        if v:
            return str(v.group(1)) == "true"
        else:
            xenrt.XRTError("Unable to parse dcbtool output")
    
    def blacklistNIC(self,pif):
        driver = self.host.execdom0("readlink /sys/class/net/%s/device/driver/module" % pif).strip().split("/")[-1]
        version = self.host.execdom0("cat /sys/class/net/%s/device/driver/module/version" % pif).strip()
        self.host.execdom0("echo %s:%s >> %s" %(driver,version,self.BLACKLIST_FILE))
                
    def checkBlacklistedNIC(self,pif):
        pifuuid = self.host.execdom0("xe pif-list params=uuid device=%s minimal=true" % pif).strip()
        val = self.host.execdom0("xe pif-param-get param-name=capabilities uuid=%s" % pifuuid).strip()
        if val == "fcoe":
            raise xenrt.XRTFailure("Blacklisted %s is showing up as FCOE capable" % pif)
        else:
            xenrt.TEC().logverbose("Blacklisted %s is not showing up as FCOE capable" % pif)

    def run(self,arglist=None):
        self.pifs = self.host.execdom0('xe pif-list params=device minimal=true')[:-1].split(",")
        fcoeCapablePifs = []
        
        for pif in self.pifs:
            if self.isNICFCOECapable(pif):
                self.blacklistNIC(pif)
                fcoeCapablePifs.append(pif)
            else:
                xenrt.TEC().logverbose("%s is not FCOE capable" % pif)
        
        if fcoeCapablePifs:
            self.host.reboot()
            for pif in fcoeCapablePifs:
                self.checkBlacklistedNIC(pif)
        

    def postRun(self):
        xenrt.TEC.log("Removing the FCOE blacklist file")
        self.host.execdom0("rm -f %s || true" % self.BLACKLIST_FILE)
        if self.sr:
            self.sr.remove()
