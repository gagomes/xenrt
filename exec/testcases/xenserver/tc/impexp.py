#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for import/export features
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, os, os.path, copy, re, time
import xenrt

class _ImpExpBase(xenrt.TestCase):
    """Base class for Import/Export testcases"""

    DISTRO = None
    ARCH = None
    CLIDISTRO = None
    USEGUI = False
    UNINSTALL_ORIGINAL = True
    IMPORT_WITH_PRESERVE = True
    IMPORT_COUNT = 1
    CHECK_IMPORTED_GUESTS = True
    SRTYPE = None
    SRTYPE_IMPORT = None
    DISKSIZE = None # Default
    
    cliguest = None
    exportLocation = ""
    guipath = None
    guiexe = None
    guild = None

    def __init__(self,tcid=None):
        self.host = None
        self.guest = None
        self.importedGuests = []
        self.guestsToClean = []
        self.image = None
        self.importsr = None
        xenrt.TestCase.__init__(self, tcid)

    def prepare(self, arglist):
        args = self.parseArgsKeyValue(arglist)
        self.SRTYPE = args.get("srtype", self.SRTYPE)

    def preExportHook(self, guest):
        pass

    def postImportHook(self, guestlist):
        pass

    def run(self,arglist):
        host = self.getDefaultHost()
        self.host = host
        self.preRun(host)
        guest = self.createGuest(host,
                                 distro=self.DISTRO,
                                 srtype=self.SRTYPE,
                                 disksize=self.DISKSIZE)
        self.guest = guest
        self.guestsToClean.append(guest)

        origvifs = guest.getVIFs()

        # Now we have the guest, do the actual export.
        if guest.getState() == "UP":
            guest.shutdown()
        elif guest.getState() == "SUSPENDED":
            guest.resume()
            guest.shutdown()
        self.preExportHook(guest)
        exp = self.exportVM(guest)

        # Normalise the state of the original to shutdown
        if guest.getState() == "SUSPENDED":
            guest.resume()
        if guest.getState() == "UP":
            guest.shutdown()

        # Are we meant to uninstall original?
        if self.UNINSTALL_ORIGINAL:
            guest.uninstall()
            self.guestsToClean.remove(guest)

        # Do the import.
        for i in range(self.IMPORT_COUNT):
            g = copy.copy(guest)
            g.vifs = []
            delete = (i == self.IMPORT_COUNT)
            self.importVM(host,g,exp,delete=delete)
            self.guestsToClean.append(g)
            self.importedGuests.append(g)

        # Cleanup the exported image if necessary.
        if self.image:
            if os.path.exists(self.image):
                os.unlink(self.image)

        self.postImportHook(self.importedGuests)

        # Start the guests and do some checks.
        if self.CHECK_IMPORTED_GUESTS:
            for g in self.importedGuests:
                g.start()
                if self.IMPORT_WITH_PRESERVE:
                    newvifs = g.getVIFs()
                    for vif in origvifs:
                        if origvifs[vif][0] != newvifs[vif][0]:
                            raise xenrt.XRTFailure("MAC address not preserved of "
                                                   "imported preserve=true guest.")
                g.check()

        if not self.UNINSTALL_ORIGINAL:
            guest.start()
            guest.check()

    def createGuest(self, host, distro=None, arch=None, srtype=None, disksize=None):
        """Create a guest to be exported, return the guest object"""
        sr = None
        if srtype:
            srs = host.getSRs(type=srtype)
            if not srs:
                raise xenrt.XRTError("No %s SR found on host." % (srtype))
            sr = srs[0]
        if not distro:
            if disksize:
                raise xenrt.XRTError("TC does not support override of "
                                     "disk size for default distro")
            guest = host.createGenericLinuxGuest(arch=arch, sr=sr)
            self.getLogsFrom(guest)
            guest.preCloneTailor()
            return guest
        elif distro in ["debian","sarge","etch"]:            
            if disksize:
                raise xenrt.XRTError("TC does not support override of "
                                     "disk size for legacy Debian VMs")
            guest = host.guestFactory()(xenrt.randomGuestName(),
                                        host.getTemplate(distro),
                                        password=xenrt.TEC().lookup("ROOT_PASSWORD_DEBIAN"))
            self.getLogsFrom(guest)
            guest.install(host, distro=distro, sr=sr)
            guest.check()
            return guest
        else:
            if not arch:
                if re.search(r"64$", distro):
                    arch = "x86-64"
                else:
                    arch = "x86-32"
            disks = []
            if disksize:
                disks.append(("0", disksize, False))
            guest = xenrt.lib.xenserver.guest.createVM(host,
                                                       xenrt.randomGuestName(),
                                                       distro,
                                                       arch=arch,
                                                       sr=sr,
                                                       vifs=[("0",
                                                        host.getPrimaryBridge(),
                                                        xenrt.randomMAC(),
                                                        None)],
                                                       disks=disks)
            self.getLogsFrom(guest)
            if guest.windows:
                guest.installDrivers()

            return guest

    def importVM(self,host,guest,image,delete=False):
        if self.importsr:
            sruuid = self.importsr
        elif self.SRTYPE or self.SRTYPE_IMPORT:
            if self.SRTYPE_IMPORT:
                srtype = self.SRTYPE_IMPORT
            else:
                srtype = self.SRTYPE
            srs = host.getSRs(type=srtype)
            if not srs:
                raise xenrt.XRTError("No %s SR found on host." % (srtype))
            sruuid = srs[0]
        else:
            sruuid = self.cliguest.chooseSR() # TODO this should query host
        if self.cliguest.windows:
            if self.USEGUI:
                # Use the windows GUI
                raise xenrt.XRTError("Unimplemented")
            else:
                # Use the windows CLI
                args = []
                args.append("xe.exe -s %s -u root -pw %s" %
                            (host.getIP(),host.password))
                args.append("vm-import")
                args.append("sr-uuid=%s" % (sruuid))
                args.append("filename=\"%s\"" % (image))
                if self.IMPORT_WITH_PRESERVE:
                    args.append("preserve=true")
                try:
                    data = self.cliguest.xmlrpcExec(string.join(args),
                                                    timeout=7200,
                                                    returndata=True).strip()
                except xenrt.XRTException, e:
                    # See if it's the cliguest that's broken
                    try:
                        self.cliguest.checkHealth()
                    except xenrt.XRTFailure, f:
                        raise xenrt.XRTError("CLI guest broken: %s" % (str(f)),
                                             f.data)
                    raise e
                # Find the uuid from data (should be the last line)
                datalines = data.split("\n")
                guest.uuid = datalines[-1].strip()

                guest.existing(host)
                host.addGuest(guest)
                if delete:
                    self.cliguest.xmlrpcExec("del /f %s" % (image))
        else:
            # Use the linux CLI
            args = []
            args.append("sr-uuid=%s" % (sruuid))
            args.append("filename=%s" % (image))
            if self.IMPORT_WITH_PRESERVE:
                args.append("preserve=true")
            c = xenrt.lib.xenserver.buildCommandLine(host,
                                                     "vm-import",
                                                     string.join(args))
            try:
                newuuid = string.strip(self.cliguest.execcmd("xe %s" % (c), 
                                                             timeout=3600))
            except xenrt.XRTException, e:
                # See if it's the cliguest that's broken
                try:
                    self.cliguest.checkHealth()
                except xenrt.XRTFailure, f:
                    raise xenrt.XRTError("CLI guest broken: %s" % (str(f)),
                                         f.data)
                raise e
            guest.uuid = newuuid
            guest.existing(host)
            host.addGuest(guest)
            if delete:
                self.cliguest.execcmd("rm -f %s" % (image))

    def exportVM(self,guest):
        if self.cliguest.windows:
            if self.USEGUI:
                # Use the windows GUI
                filename = "c:\\\\export-%s.img" % (guest.getUUID())
                args = []
                args.append("cd %s\n" % (self.guipath))
                args.append(self.guiexe)
                if self.cliguest.xmlrpcFileExists(\
                    "c:\\XenCenterTestResources\\export.testrun"):
                    args.append("runtests testrun=\"export.testrun\"")
                else:
                    args.append("runtests export=true")
                args.append("host=\"%s\"" % (guest.host.getIP()))
                args.append("username=root")
                args.append("password=%s" % (guest.host.password))
                args.append("vm=\"%s\"" % (guest.getName()))
                args.append("filename=\"%s\"" % (filename))
                args.append("disable_help_tests=true")
                args.append("disable_dependency_resolution=true")
                args.append("log_directory=\"%s\"" % (self.guild))
                args.append("--wait")

                try:
                    data = self.cliguest.xmlrpcExec(string.join(args),
                                                    timeout=7200,
                                                    returndata=True)
                except xenrt.XRTException, e:
                    # See if it's the cliguest that's broken
                    try:
                        self.cliguest.checkHealth()
                    except xenrt.XRTFailure, f:
                        raise xenrt.XRTError("CLI guest broken: %s" % (str(f)),
                                             f.data)
                    raise e

                filename = string.replace(filename,"\\\\","\\")

                if not self.cliguest.xmlrpcFileExists(filename, patient=True):
                    raise xenrt.XRTFailure("Export image file %s does not "
                                           "exist" % (filename))

                # Currently don't have import via GUI ability, so use CLI
                self.USEGUI = False

                # Remove the \\ from the filename, as that will confuse del
                return filename
            else:
                # Use the windows CLI
                filename = "c:\\export-%s.img" % (guest.getUUID())
                args = []
                args.append("xe.exe -s %s -u root -pw %s" %
                            (guest.host.getIP(),guest.host.password))
                args.append("vm-export")
                args.append("filename=\"%s\"" % (filename))
                args.append("uuid=%s" % (guest.getUUID()))
                if guest.special.has_key('export suspended VM uses '
                                         '--preserve-power-state') \
                        and guest.getState() == "SUSPENDED":
                    args.append("--preserve-power-state")
                try:
                    self.cliguest.xmlrpcExec(string.join(args),
                                             timeout=7200,
                                             returndata=True)
                except xenrt.XRTException, e:
                    # See if it's the cliguest that's broken
                    try:
                        self.cliguest.checkHealth()
                    except xenrt.XRTFailure, f:
                        raise xenrt.XRTError("CLI guest broken: %s" % (str(f)),
                                             f.data)
                    raise e

                return filename
        else:
            # Use the linux CLI
            filename = "%s/export-%s.img" % (self.exportLocation,guest.getUUID())
            args = []
            args.append("uuid=%s" % (guest.getUUID()))
            args.append("filename=%s" % (filename))
            if guest.special.has_key('export suspended VM uses '
                                     '--preserve-power-state') \
                    and guest.getState() == "SUSPENDED":
                args.append("--preserve-power-state")
            c = xenrt.lib.xenserver.buildCommandLine(guest.host,
                                                     "vm-export",
                                                     string.join(args))
            self.cliguest.execcmd("xe %s" % (c), timeout=3600)
            return filename


    def preRun(self, host):
        self.cliguest = self.createGuest(host, distro=self.CLIDISTRO, arch=self.ARCH)
        self.guestsToClean.append(self.cliguest)
        if self.CLIDISTRO in ["debian","sarge","etch"] or not self.CLIDISTRO:
            # Need to add an extra disk, as root one is too small
            if self.DISKSIZE:
                sizebytes = (self.DISKSIZE + 2) * xenrt.GIGA
            else:
                sizebytes = 30 * xenrt.GIGA
            ud = self.cliguest.createDisk(sizebytes=sizebytes)
            d = host.parseListForOtherParam("vbd-list", 
                                            "vm-uuid", 
                                             self.cliguest.getUUID(), 
                                            "device", 
                                            "userdevice=%s" % (ud))
            time.sleep(5)
            self.cliguest.execguest("mkdir -p /mnt/export")
            self.cliguest.execguest("mkfs.ext3 /dev/%s" % (d))
            self.cliguest.execguest("mount /dev/%s /mnt/export" % (d))
            self.exportLocation = "/mnt/export"

        if self.cliguest.windows:
            if self.USEGUI:
                # Install the GUI
                self.cliguest.installCarbonWindowsGUI()
                self.guipath, self.guiexe = self.cliguest.findCarbonWindowsGUI()
                # Create a log dir
                self.guild = self.remoteLoggingDirectory(self.cliguest)
                # Temporary until we can import through GUI as well
                self.cliguest.xmlrpcExec("copy \"%s\\xe.exe\" c:\\windows\\xe.exe" % (self.guipath))
                self.cliguest.xmlrpcExec("copy \"%s\\*.dll\" c:\\windows" % (self.guipath))
            else:
                self.cliguest.installCarbonWindowsCLI()
        else:
            self.cliguest.installCarbonLinuxCLI()

    def postRun(self):
        # Get rid of any guests we installed, and remove any locally created
        # images from controller
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
 
        if self.image:
            if os.path.exists(self.image):
                try:
                    os.unlink(self.image)
                except:
                    xenrt.TEC().warning("Unable to remove exported image %s "
                                        "from controller" % (self.image))

class _PoolImpExp(_ImpExpBase):

    EXPORTFROMSLAVE = True
    IMPORTTOSLAVE = True 

    def run(self,arglist):
        self.pool = self.getDefaultPool()

        if self.EXPORTFROMSLAVE:
            self.exporthost = xenrt.TEC().registry.hostGet("RESOURCE_HOST_1")
        else:
            self.exporthost = self.pool.master

        if self.IMPORTTOSLAVE:
            self.importhost = xenrt.TEC().registry.hostGet("RESOURCE_HOST_1")
        else:
            self.importhost = self.pool.master

        # Determine if we are using LVM or EXT for local SRs
        localsr = self.pool.master.getLocalSR()
        localsrtype = self.pool.master.genParamGet("sr", localsr, "type")

        if self.SRTYPE:
            srtype = self.SRTYPE
        else:
            srtype = localsrtype
        self.exportsr = self.pool.master.parseListForUUID(\
            "sr-list", 
            "host", 
            self.exporthost.getMyHostName(), 
            "type=%s" % (srtype))

        if self.SRTYPE_IMPORT:
            srtype = self.SRTYPE_IMPORT
        elif self.SRTYPE:
            srtype = self.SRTYPE
        else:
            srtype = localsrtype
        self.importsr = self.pool.master.parseListForUUID(\
            "sr-list", 
            "host", 
            self.importhost.getMyHostName(), 
            "type=%s" % (srtype))
        try:
            self.preRun(self.pool.master)
            self.guest = self.createGuest(self.exporthost)
            self.guestsToClean.append(self.guest)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError(e.reason)

        origvifs = self.guest.getVIFs()

        if self.guest.getState() == "UP":
            self.guest.shutdown()

        self.preExportHook(self.guest)
        filename = "%s/export-%s.img" % (self.exportLocation, 
                                         self.guest.getUUID())
        args = "uuid=%s filename=%s" % (self.guest.getUUID(), 
                                        filename)
        c = xenrt.lib.xenserver.buildCommandLine(self.pool.master,
                                                "vm-export",
                                                 args)
        self.cliguest.execcmd("xe %s" % (c), timeout=3600)

        if self.guest.getState() == "SUSPENDED":
            self.guest.resume()
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        self.guest.uninstall()
        self.guestsToClean.remove(self.guest)

        self.imported = copy.copy(self.guest)
        self.imported.vifs = []
        args = []
        args.append("sr-uuid=%s" % (self.importsr))
        args.append("filename=%s" % (filename))
        args.append("preserve=true")
        c = xenrt.lib.xenserver.buildCommandLine(self.pool.master,
                                                "vm-import",
                                                 string.join(args))
        self.imported.uuid = string.strip(self.cliguest.execcmd("xe %s" % (c), 
                                                                 timeout=3600))
        self.imported.existing(self.importhost)

        self.cliguest.execcmd("rm -f %s" % (filename))
        self.guestsToClean.append(self.imported)
        self.postImportHook([self.imported])

        self.imported.start()

        newvifs = self.imported.getVIFs()
        for vif in origvifs:
            if origvifs[vif][0] != newvifs[vif][0]:
                raise xenrt.XRTFailure("MAC address not preserved of "
                                       "self.imported preserve=true guest.")
        self.imported.check()

class _WindowsCLI(_PoolImpExp):

    def prepare(self, arglist):
        _PoolImpExp.prepare(self, arglist)
        self.pool = self.getDefaultPool()
        self.cliguest = self.pool.master.createGenericWindowsGuest()
        xenrt.TEC().registry.write("/xenrt/cli/windows", True) 
        xenrt.TEC().registry.write("/xenrt/cli/windows_guest", self.cliguest) 
        xenrt.lib.xenserver.cli.clearCacheFor(self.cliguest.host.machine)

    def postRun(self):
        _PoolImpExp.postRun(self)
        xenrt.TEC().registry.delete("/xenrt/cli/windows")
        xenrt.TEC().registry.delete("/xenrt/cli/windows_guest")
        xenrt.lib.xenserver.cli.clearCacheFor(self.cliguest.host.machine)
        try: self.cliguest.shutdown()
        except: pass
        try: self.cliguest.uninstall()
        except: pass

class TC8361(_PoolImpExp):
    """Export and import of a VM on slave local storage."""

    EXPORTFROMSLAVE = True
    IMPORTTOSLAVE = True 

class TC1217(_WindowsCLI):
    """Export/Import of a VM installed on master local storage (using Windows CLI)"""

    EXPORTFROMSLAVE = False
    IMPORTTOSLAVE = False 

class TC1218(_WindowsCLI):
    """Export/Import of a VM installed on slaves local storage (using Windows CLI)"""

    EXPORTFROMSLAVE = True
    IMPORTTOSLAVE = True 

class TC1219(_PoolImpExp):
    """Export and import of a VM on master local storage."""

    EXPORTFROMSLAVE = False
    IMPORTTOSLAVE = False 

class TC8362(_PoolImpExp):
    """Export of a VM from local storage on a slave, 
       import to local storage on the master."""

    EXPORTFROMSLAVE = True
    IMPORTTOSLAVE = False 

class TC8363(_PoolImpExp):
    """Export of a VM from local storage on a master, 
       import to local storage on the slave."""

    EXPORTFROMSLAVE = False
    IMPORTTOSLAVE = True

class TC9176(_ImpExpBase):
    """Export of a suspended VM from local storage on a master, import to local storage on a slave"""

    EXPORTFROMSLAVE = False
    IMPORTTOSLAVE = True

    def preExportHook(self, guest):
        xenrt.TEC().logverbose("Starting and then suspending VM before export")
        guest.start()
        guest.suspend()

    def postImportHook(self, guestlist):
        xenrt.TEC().logverbose("Resuming and shutting down all imported VMs")
        for g in guestlist:
            if g.getState() != "SUSPENDED":
                raise xenrt.XRTFailure("Imported VM is not in the suspended "
                                       "state", g.getName())
            g.resume()
            g.shutdown()

class TC7303(_ImpExpBase):
    """Import/export of a corrupted image."""
    CHECK_IMPORTED_GUESTS = False
        
    def importVM(self, host, guest, image, delete=False):
        try: _ImpExpBase.importVM(self, host, guest, image, delete)
        except Exception, e:
            if not re.search(r"checksum failed", e.data):
                raise xenrt.XRTFailure("Import failed but didn't mention "
                                       "checksum failure (%s)." % (e.data))
        else: raise xenrt.XRTFailure("Import of corrupt image succeeded.")
    
    def exportVM(self, guest):
        image = _ImpExpBase.exportVM(self, guest)
        byte = 150000000
        xenrt.TEC().logverbose("Flipping a bit in byte %s of image." % (byte))
        self.cliguest.execguest("ls -l %s" % (image))
        self.cliguest.execguest("sha1sum %s" % (image))
        self.cliguest.execguest("%s/progs/flipbit %s %s" %
                                (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"),
                                 byte, image))
        self.cliguest.execguest("ls -l %s" % (image))
        self.cliguest.execguest("sha1sum %s" % (image))
        return image

class TC11203(TC7303):   
    CLIDISTRO="centos56"
 
class TC6826(_ImpExpBase):
    """Basic functional import/export test (preserve=true)"""

class TC6827(_ImpExpBase):
    """Basic functional import/export test (preserve=false)"""
    IMPORT_WITH_PRESERVE = False

class TC6828(_ImpExpBase):
    """Basic functional import/export test (keep original)"""
    IMPORT_WITH_PRESERVE = False
    UNINSTALL_ORIGINAL = False

class TC6829(_ImpExpBase):
    """Basic functional import/export test (multiple imports)"""
    IMPORT_WITH_PRESERVE = False
    IMPORT_COUNT = 2

class TC6830(_ImpExpBase):
    """Basic functional import/export test (extra VIFs+VBDs)"""

    def createGuest(self, host, distro=None, arch=None, srtype=None, disksize=None):
        g = _ImpExpBase.createGuest(self,
                                    host,
                                    distro=distro,
                                    arch = arch,
                                    srtype=srtype,
                                    disksize=disksize)
        # Add additional VIF and VBD
        g.createDisk(sizebytes=104857600) # 100MB
        g.createVIF(None,None,None) # Defaults
        # Set non default memory and vcpus
        mem = g.memget() # in MB
        vcpus = g.cpuget()

        g.shutdown()
        g.memset(mem+128)
        g.cpuset(vcpus+1)
        g.start()

        return g

class TC9175(_ImpExpBase):
    """Export and import of a suspended VM from and to a local SR"""

    def preExportHook(self, guest):
        xenrt.TEC().logverbose("Starting and then suspending VM before export")
        guest.start()
        guest.suspend()

    def postImportHook(self, guestlist):
        xenrt.TEC().logverbose("Resuming and shutting down all imported VMs")
        for g in guestlist:
            if g.getState() != "SUSPENDED":
                raise xenrt.XRTFailure("Imported VM is not in the suspended "
                                       "state", g.getName())
            g.resume()
            g.shutdown()

class TC6831(_ImpExpBase):
    """Import/Export test of Windows 2003EE SP2 guest"""
    DISTRO = "w2k3eesp2"

class TC6832(_ImpExpBase):
    """Import/Export test of Windows 2003EE SP2 x64 guest"""
    DISTRO = "w2k3eesp2-x64"

class TC9978(_ImpExpBase):
    """Import/Export test of Windows Server 2008 R2 x64 guest"""
    DISTRO = "ws08r2-x64"
    
class TC12562(_ImpExpBase):
    """Import/Export test of Windows Server 2008 R2 SP1 x64 guest"""
    DISTRO = "ws08r2sp1-x64"
    
class TC27335(_ImpExpBase):
    """Import/Export test of Windows 10 32-bit guest"""
    DISTRO = "win10-x86"
    
class TC27336(_ImpExpBase):
    """Import/Export test of Windows 10 64-bit guest"""
    DISTRO = "win10-x64"
    
class TC6833(_ImpExpBase):
    """Import/Export test of Debian guest"""
    DISTRO = "debian60"

class TC6834(_ImpExpBase):
    """Import/Export test of RHEL 4.4 guest"""
    DISTRO="rhel5"

class TC6835(_ImpExpBase):
    """Import/Export test of RHEL 4.8 guest"""
    DISTRO="rhel48"

class TC6836(_ImpExpBase):
    """Import/Export test of RHEL 5.1 guest"""
    DISTRO="rhel51"

class TC9942(_ImpExpBase):
    """Import/Export test of RHEL 5.3 guest"""
    DISTRO="rhel53"

class TC10976(_ImpExpBase):
    """Import/Export test of RHEL 5.4 guest"""
    DISTRO="rhel54"

class TC12563(_ImpExpBase):
    """Import/Export test of RHEL 5.5 guest"""
    DISTRO="rhel55"

class TC6837(_ImpExpBase):
    """Import/Export test of SLES 10 SP1 guest"""
    DISTRO="sles102"

class TC12568(_ImpExpBase):
    """Import/Export test of SLES 11 SP1 guest"""
    DISTRO="sles111"

class TC6838(_ImpExpBase):
    """Import/Export test using CLI on Debian"""
    CLIDISTRO = "debian60"

class TC6839(_ImpExpBase):
    """Import/Export test using CLI on RHEL 5.1"""
    CLIDISTRO="rhel5"

class TC9941(_ImpExpBase):
    """Import/Export test using CLI on RHEL 5.3"""
    CLIDISTRO="rhel53"

class TC10979(_ImpExpBase):
    """Import/Export test using CLI on RHEL 5.4"""
    CLIDISTRO="rhel54"

class TC12564(_ImpExpBase):
    """Import/Export test using CLI on RHEL 5.5"""
    CLIDISTRO="rhel55"

class TC19935(_ImpExpBase):
    """Import/Export test using CLI on RHEL 6.3"""
    CLIDISTRO="rhel63"

class TC9040(_ImpExpBase):
    """Import/Export test using CLI on SLES 11 SP2"""
    CLIDISTRO="sles112"

class TC12565(_ImpExpBase):
    """Import/Export test using CLI on SLES 11 SP1"""
    CLIDISTRO="sles111"

class TC26943(_ImpExpBase):
    """Import/Export test using CLI on CENTOS 7"""
    CLIDISTRO = "centos7"
    ARCH = "x86-64"

class TC6840(_ImpExpBase):
    """Import/Export test using CLI on Windows 2003 EE SP2"""
    CLIDISTRO="w2k3eesp2"

class TC6841(_ImpExpBase):
    """Import/Export test using CLI on Windows 2003 EE SP2 x64"""
    CLIDISTRO="w2k3eesp2-x64"

class TC6842(_ImpExpBase):
    """Import/Export test using CLI on Windows XP SP3"""
    CLIDISTRO="winxpsp3"

class TC9979(_ImpExpBase):
    """Import/Export test using CLI on Windows 7"""
    CLIDISTRO="win7-x86"

class TC9980(_ImpExpBase):
    """Import/Export test using CLI on Windows 7 x64"""
    CLIDISTRO="win7-x64"

class TC12566(_ImpExpBase):
    """Import/Export test using CLI on Windows 7 SP1"""
    CLIDISTRO="win7sp1-x86"

class TC12567(_ImpExpBase):
    """Import/Export test using CLI on Windows 7 SP1 x64"""
    CLIDISTRO="win7sp1-x64"

class TC6843(_ImpExpBase):
    """Import/Export test using GUI on Windows 2003 EE SP2"""
    CLIDISTRO="w2k3eesp2"
    USEGUI = True

class TC6844(_ImpExpBase):
    """Import/Export test using GUI on Windows 2003 EE SP2 x64"""
    CLIDISTRO="w2k3eesp2-x64"
    USEGUI = True

class TC6845(_ImpExpBase):
    """Import/Export test using GUI on Windows XP SP2"""
    CLIDISTRO="winxpsp2"
    USEGUI = True

class TC19932(_ImpExpBase):
    """Import/Export test using CLI on Windows 8"""
    CLIDISTRO="win8-x86"

class TC19933(_ImpExpBase):
    """Import/Export test using CLI on Windows 8 x64"""
    CLIDISTRO="win8-x64"

class TC19934(_ImpExpBase):
    """Import/Export test using CLI on Windows Server 2012 x64"""
    CLIDISTRO="ws12-x64"

class TC10627(_ImpExpBase):
    """Import/Export test of a 20GB VM on Equallogic SR (thick provisioned)"""
    DISTRO = "rhel54" # See SCTX-360
    SRTYPE = "equal"
    DISKSIZE = 20 # GB

class TC10670(_ImpExpBase):
    """Import/Export test of a 20GB VM on Equallogic SR (thick provisioned)"""
    DISTRO = "rhel54" # See SCTX-360
    SRTYPE = "equal"
    DISKSIZE = 20 # GB

class TC10628(_ImpExpBase):
    """Import/Export test of a 20GB VM on NetApp SR"""
    DISTRO = "rhel54" # See SCTX-360
    SRTYPE = "netapp"
    DISKSIZE = 20 # GB

class TC10629(_ImpExpBase):
    """Import/Export test of a 20GB VM on NFS SR"""
    DISTRO = "rhel5x" # See SCTX-360
    SRTYPE = "nfs"
    DISKSIZE = 20 # GB

class TC20936(_ImpExpBase):
    """Import/Export test of a 20GB VM on file SR"""
    DISTRO = "rhel54" # See SCTX-360
    SRTYPE = "file"
    DISKSIZE = 20 # GB


class TC10668(_ImpExpBase):
    """Export a VM from an LVM SR and import to a Equallogic SR (thin provisioned)"""
    DISTRO = "rhel54"
    SRTYPE = "lvm"
    SRTYPE_IMPORT = "equal"
    DISKSIZE = 4 # GB

class TC10669(_ImpExpBase):
    """Export a VM from an LVM SR and import to a Equallogic SR (thick provisioned)"""
    DISTRO = "rhel54"
    SRTYPE = "lvm"
    SRTYPE_IMPORT = "equal"
    DISKSIZE = 4 # GB

class TC18491(xenrt.TestCase):
    """Importing a VM for more than 24 hours should not fail"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.getGuest("vm")
        
        webDir = xenrt.WebDirectory()
        webDir.copyIn(xenrt.TEC().getFile("/usr/groups/xenrt/v6/v6vpx11-12-1_unzipped.xva"))
        self.guest.execguest("cd / && wget %s" % webDir.getURL("v6vpx11-12-1_unzipped.xva"))
        
        # install NFS server on guest
        self.guest.execguest("apt-get install -y --force-yes nfs-kernel-server nfs-common portmap")
        self.guest.execguest("echo '/ *(ro,sync,no_root_squash,insecure,subtree_check)' > /etc/exports")
        self.guest.execguest("/etc/init.d/portmap start || /etc/init.d/rpcbind start")
        self.guest.execguest("/etc/init.d/nfs-common start || true")
        self.guest.execguest("/etc/init.d/nfs-kernel-server start || true")

        # connect host to VM's nfs
        self.host.execdom0("mkdir /mnt/nfs")
        self.host.execdom0("mount %s:/ /mnt/nfs" % self.guest.getIP())
        
        # slow VIF down to a crawl
        self.guest.setVIFRate("eth0", 1)
        self.guest.unplugVIF("eth0")
        self.guest.plugVIF("eth0")
        
    def run(self, arglist):
        
        # start long running import going.
        self.host.execdom0("xe vm-import filename=/mnt/nfs/v6vpx11-12-1_unzipped.xva > /dev/null 2>&1 </dev/null &")
        
        # sleep for 23 hours, 59 mins
        time.sleep((24 * 3600) - 1)
        
        # return vif-rate to normal
        self.guest.setVIFRate("eth0", None)
        self.guest.unplugVIF("eth0")
        self.guest.plugVIF("eth0")
        
        for i in range(30):
            if len(self.host.listGuests()) == 2:
                return
            time.sleep(60)
        
        raise xenrt.XRTFailure("Long VM import failed.")
