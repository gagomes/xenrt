#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer host installation test cases
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import string, time, re, os.path, random
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.cli
import XenAPI
from xenrt.lazylog import log, warning

class TCXenServerInstall(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCXenServerInstall")
        self.blocker = True
        self.mountList = []

    def run(self, arglist=None):
        license = xenrt.TEC().lookup("OPTION_APPLY_LICENSE",
                                     True,
                                     boolean=True)
        machine = "RESOURCE_HOST_0"
        source = xenrt.TEC().lookup("HOST_INSTALL_METHOD", "url")
        hosttype = xenrt.TEC().lookup("PRODUCT_VERSION", None)
        nosr = False
        nfs = None
        lun = None
        slave = False
        inputdir = None
        extracds = None
        diskcount = 1
        multi = False
        installSRType = None
        timezone = "UTC"
        ntpserver = None
        noprepare = False
        netapp = False
        eql = False
        fcsr = None
        fcoesr = None
        sassr = None
        iscsihbasr = None
        bootloader = xenrt.TEC().lookup("HOST_BOOTLOADER", None)
        ipv6_mode = None
        
        if arglist:
            for i in range(len(arglist)):
                arg = arglist[i]
                l = string.split(arg, "=", 1)
                if len(l) == 1 and i == 0:
                    # First argument can be the machine name
                    machine = arg
                elif l[0] == "source":
                    source = l[1]
                elif l[0] == "Orlando" or l[0] == "orlando":
                    hosttype = "Orlando"
                elif string.lower(l[0]) == "nosr":
                    nosr = True
                elif l[0] == "nfs":
                    nfs = "yes"
                elif l[0] == "iscsi":
                    if len(l) == 1:
                        lun = "yes"
                    else:
                        lun = l[1]
                elif l[0] == "slave":
                    slave = True
                elif l[0] == "input":
                    inputdir = l[1]
                elif l[0] == "extracds":
                    extracds = l[1]
                elif l[0] == "disks":
                    diskcount = int(l[1])
                elif l[0] == "multi":
                    multi = True
                elif l[0] in ("lvm", "ext"):
                    installSRType = l[0]
                elif l[0] == "timezone":
                    timezone = l[1]
                elif l[0] == "netapp":
                    netapp = True
                elif l[0] == "eql":
                    eql = True
                elif l[0] == "ntpserver":
                    ntpserver = l[1]
                elif l[0] == "noprepare":
                    noprepare = True
                elif l[0] == "fc" or l[0] == "FC":
                    fcsr = "yes"
                elif l[0] == "fcoe" or l[0] == "FCOE":
                    fcoesr = "yes"
                elif l[0] == "sas" or l[0] == "SAS":
                    sassr = "yes"
                elif l[0] == "iscsihba" or l[0] == "ISCSIHBA":
                    iscsihbasr = "yes"
                elif l[0] == "bootloader":
                    bootloader = l[1]
                elif l[0] == "ipv6":
                    ipv6_mode = l[1]
                    
        if not multi:
            # The machine name might be a variable we need to look up
            mname = xenrt.TEC().lookup(machine, machine)
            m = xenrt.PhysicalHost(mname)
            xenrt.GEC().startLogger(m)
            host = xenrt.lib.xenserver.hostFactory(hosttype)(m, productVersion=hosttype)

        # If we supplied an inputdir we use this as a sticky override
        # for INPUTDIR
        if inputdir:
            if inputdir == "DEFAULT":
                xenrt.TEC().setInputDir(None)
            else:
                xenrt.TEC().setInputDir(inputdir)

        # For a multihost install we'll unpack the ISO and let each
        # install use the same bits.
        packdir = None
        if multi:
            hosts = []
            forreg = []
            i = 0
            while True:
                mname = xenrt.TEC().lookup("RESOURCE_HOST_%u" % (i), None)
                if not mname:
                    break
                m = xenrt.PhysicalHost(mname)
                xenrt.GEC().startLogger(m)
                host = xenrt.lib.xenserver.hostFactory(hosttype)(m, productVersion=hosttype)
                hosts.append(host)
                forreg.append(("RESOURCE_HOST_%u" % (i), host))
                i = i + 1
            xenrt.TEC().comment("Installing multiple hosts: %s" %
                                (string.join(map(lambda x:x.getName(), hosts),
                                             ", ")))
        else:
            hosts = [host]

        # Start the install
        tocomplete = []
        installs = []

        for host in hosts:
            interfaces = []
            ipv6_addr = None
            gateway6 = None

            if ipv6_mode == "static":
                ipv6_addr = host.lookup("HOST_ADDRESS6")
                gateway6 = host.lookup(["NETWORK_CONFIG", "DEFAULT", "GATEWAY6"])
                
            interfaces.append((None, "yes", "dhcp", None, None, None, ipv6_mode, ipv6_addr, gateway6))
            if nosr:
                disks = []
                primarydisk = host.getInstallDisk(ccissIfAvailable=host.USE_CCISS, legacySATA=(not host.isCentOS7Dom0()))
            else:
                disks = host.getGuestDisks(count=diskcount, ccissIfAvailable=host.USE_CCISS, legacySATA=(not host.isCentOS7Dom0()))
                primarydisk= host.getInstallDisk(ccissIfAvailable=host.USE_CCISS, legacySATA=(not host.isCentOS7Dom0()))

            self.getLogsFrom(host)
            if xenrt.TEC().lookup(["CLIOPTIONS", "NOPREPARE"], False,
                                  boolean=True) or noprepare:
                host.checkVersion()
                host.existing()
                xenrt.TEC().registry.hostPut(machine, host)
                xenrt.TEC().skip("Skipping because of --noprepare option")
            else:
                if bootloader:
                    kwargs = {"bootloader": bootloader}
                else:
                    kwargs = {}
                handle = host.install(interfaces=interfaces,
                                      primarydisk=primarydisk,
                                      guestdisks=disks,
                                      source=source,
                                      extracds=extracds,
                                      async=multi,
                                      installSRType=installSRType,
                                      timezone=timezone,
                                      ntpserver=ntpserver,
                                      **kwargs)
                if multi:
                    tocomplete.append((host,
                                       handle,
                                       interfaces,
                                       primarydisk,
                                       disks))
                    installs.append((host, handle))
                else:
                    time.sleep(180)
                    host.check(interfaces=interfaces,
                               primarydisk=primarydisk,
                               guestdisks=disks,
                               timezone=timezone,
                               ntpserver=ntpserver)
                                    
        if xenrt.TEC().lookup(["CLIOPTIONS", "NOPREPARE"], False,
                              boolean=True) or noprepare:
            return

        # Wait for installer completion on each host (if multi)
        if multi:
            xenrt.lib.xenserver.watchForInstallCompletion(installs)

        # For multihost installs run the completions
        for x in tocomplete:
            host, handle, interfaces, primarydisk, disks = x
            host.installComplete(handle)
            host.check(interfaces=interfaces,
                       primarydisk=primarydisk,
                       guestdisks=disks,
                       timezone=timezone,
                       ntpserver=ntpserver)

        if not xenrt.TEC().lookup("OPTION_NO_AUTO_PATCH", False, boolean=True):
            for host in hosts:
                host.applyRequiredPatches()

        # If we unpacked the ISO then remove the directory
        if packdir:
            packdir.remove()

        if license:
            for host in hosts:
                host.license()

        if multi:
            for x in forreg:
                machine, host = x
                xenrt.TEC().registry.hostPut(machine, host)
        else:
            xenrt.TEC().registry.hostPut(machine, host)

        # Hacks
        alteth = xenrt.TEC().lookup("FIDDLE_INTERFACE", None)
        if alteth:
            for host in hosts:
                host.changeManagementInterface(alteth)
                
        if not slave:
            host = hosts[0]
            # Optionally switch to using NFS for VHDs
            if not nfs:
                nfs = host.lookup("SR_NFS", None)
            if nfs:
                if nfs == "yes":
                    x = xenrt.ExternalNFSShare()
                    nfs = x.getMount()
                r = re.search(r"([0-9\.]+):(\S+)", nfs)
                if not r:
                    raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfs))
                sr = xenrt.lib.xenserver.NFSStorageRepository(host,
                                                              "xenrtnfs")
                sr.create(r.group(1), r.group(2))
                sr.check()
                host.addSR(sr, default=True)
            elif host.lookup("SR_RAWNFS", False, boolean=True):
                sr = xenrt.lib.xenserver.SMAPIv3SharedStorageRepository(host, "xenrtnfs")
                sr.create(None, None)
                sr.check()
                host.addSR(sr, default=True)

            # Optionally use an ISCSI_LUN for storage
            lunobj = None
            subtype = "lvm"
            if not lun:
                lun = host.lookup("SR_ISCSI", None)
            if not lun:
                lun = host.lookup("SR_EXTOISCSI", None)
                if lun:
                    subtype = "ext"
            if not lun:
                lun = host.lookup("SR_LVHDOISCSI", None)
                if lun:
                    subtype = "lvhd"
            if not lun:
                lun = host.lookup("SR_LVMOISCSI", None)
            if lun:
                if lun == "yes":
                    ttype = None
                else:
                    ttype = lun
                minsize = int(host.lookup("SR_ISCSI_MINSIZE", 40))
                maxsize = int(host.lookup("SR_ISCSI_MAXSIZE", 1000000))
                lunobj = xenrt.lib.xenserver.ISCSILun(minsize=minsize,
                                                      maxsize=maxsize,
                                                      ttype=ttype)
            lunconf = host.lookup("USE_ISCSI", None)
            if lunconf:
                # This is an explicitly specified LUN
                lunobj = xenrt.ISCSILunSpecified(lunconf)
            if lunobj:
                multipathing = host.lookup("USE_MULTIPATH",
                                           None,
                                           boolean=True)
                thinprov = host.lookup("THIN_LVHD", False, boolean=True)
                sr = xenrt.lib.xenserver.ISCSIStorageRepository(host,
                                                                "xenrtiscsi",
                                                                thinprov)
                sr.create(lunobj, subtype=subtype, multipathing=multipathing)
                sr.check()
                host.addSR(sr, default=True)

            napp = None
            nappconf = host.lookup("USE_NETAPP", None)
            if nappconf and nappconf != "yes":
                # This is an explicitly defined target
                napp = xenrt.NetAppTargetSpecified(nappconf)
            if netapp or (nappconf and nappconf == "yes"):
                minsize = int(host.lookup("SR_NETAPP_MINSIZE", 40))
                maxsize = int(host.lookup("SR_NETAPP_MAXSIZE", 1000000))
                napp = xenrt.NetAppTarget(minsize=minsize, maxsize=maxsize)
            if napp:
                xenrt.TEC().logverbose("Using NetApp SR.")
                sr = xenrt.lib.xenserver.NetAppStorageRepository(host, 
                                                                 "xenrtnetapp")
                sr.create(napp)
                sr.check()
                host.addSR(sr, default=True)

            eqlt = None
            eqlconf = host.lookup("USE_EQL", None)
            if eqlconf and eqlconf != "yes":
                # This is an explicitly defined target
                eqlt = xenrt.EQLTargetSpecified(eqlconf)
            if eql or (eqlconf and eqlconf == "yes"):
                minsize = int(host.lookup("SR_EQL_MINSIZE", 40))
                maxsize = int(host.lookup("SR_EQL_MAXSIZE", 1000000))
                eqlt = xenrt.EQLTarget(minsize=minsize, maxsize=maxsize)
            if eqlt:
                xenrt.TEC().logverbose("Using EqualLogic SR.")
                sr = xenrt.lib.xenserver.EQLStorageRepository(host, "xenrteql")
                sr.create(eqlt)
                sr.check()
                host.addSR(sr, default=True)

            if not fcsr:
                fcsr = host.lookup("SR_FC", None)
            if fcsr:
                if fcsr == "yes":
                    fcsr = "LUN0"
                lun = xenrt.HBALun([host])
                multipathing = host.lookup("USE_MULTIPATH",
                                           False,
                                           boolean=True)
                sr = xenrt.lib.xenserver.FCStorageRepository(host, "xenrtfc")
                sr.create(lun, multipathing=multipathing)
                sr.check()
                host.addSR(sr, default=True)
            if not fcoesr:
                fcoesr = host.lookup("SR_FCOE", None)
            if fcoesr:
                lun = xenrt.HBALun([host])
                multipathing = host.lookup("USE_MULTIPATH",
                                           False,
                                           boolean=True)
                sr = xenrt.lib.xenserver.FCOEStorageRepository(host, "xenrtfcoe")
                sr.create(lun, multipathing=multipathing)
                sr.check()
                host.addSR(sr, default=True)
                
            if not sassr:
                sassr = host.lookup("SR_SAS", None)
            if sassr:
                lun = xenrt.HBALun([host])
                sr = xenrt.lib.xenserver.SharedSASStorageRepository(host,
                                                                    "xenrtsas")
                sr.create(lun)
                sr.check()
                host.addSR(sr, default=True)

            if not iscsihbasr:
                iscsihbasr = host.lookup("SR_ISCSIHBA", None)
            if iscsihbasr:
                lun = xenrt.HBALun([host])
                sr = xenrt.lib.xenserver.ISCSIHBAStorageRepository(host,
                                                                   "xenrthba")
                sr.create(lun)
                sr.check()
                host.addSR(sr, default=True)

            # Optionally create a NFS server running from the host
            if xenrt.TEC().lookup("OPTION_LOCAL_NFS", False, boolean=True):
                host.makeLocalNFSSR()

        if xenrt.TEC().lookup("TEST_INSTALLER_SSHPW", None) is not None:
            xenrt.TEC().comment("Verifying that SSH was running in installer")
            for host in hosts:
                confirm = host.execdom0('cat /ssh_succeeded.txt')
                if not confirm.startswith('yes'):
                    raise xenrt.XRTError("Installer SSH functionality not confirmed (%s)"%confirm)
                
        if xenrt.TEC().lookup("DEBUG_CA14959", False, boolean=True):
            xenrt.TEC().comment("Using CA-14959 workaround.")
            for host in hosts:
                host.execdom0("rm -f /etc/xensource/no_sm_log")
                host.execdom0("udevcontrol log_priority=\"debug\"")

        for host in hosts:
            host.applyWorkarounds()
            host.postInstall()

        # Normally preJobTests gets called on the hosts in Prepare, but as we're installing the host we need to do it ourselves
        host.preJobTests()
        xenrt.GEC().preJobTestsDone = True # Technically this is untrue, as there might be other host installs to do, but it should work anyway

                
    def postRun(self):
        for mount in self.mountList:
            try:
                mount.unmount()
            except:
                pass

class TCXenServerUpgrade(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCXenServerUpgrade")
        self.blocker = True

    def run(self, arglist=None):
        license = xenrt.TEC().lookup("OPTION_APPLY_LICENSE",
                                     True,
                                     boolean=True)
        machine = "RESOURCE_HOST_0"
        source = xenrt.TEC().lookup("HOST_INSTALL_METHOD", "url")
        hosttype = xenrt.TEC().lookup("PRODUCT_VERSION", None)
        inputdir = None
        newProductVersion = None
        extracds = None
        upgradeguest = False
        suspendVMsDuringUpgrade = False

        if arglist:
            for i in range(len(arglist)):
                arg = arglist[i]
                l = string.split(arg, "=", 1)
                if len(l) == 1 and i == 0:
                    # First argument can be the machine name
                    machine = arg
                elif l[0] == "source":
                    source = l[1]
                elif l[0] == "Rio" or l[0] == "rio":
                    hosttype = "Rio"
                elif l[0] == "input":
                    inputdir = l[1]
                elif l[0] == "extracds":
                    extracds = l[1]
                elif l[0] == "upgradeguest":
                    upgradeguest = True
                elif l[0] == "suspendDuringUpgrade":
                    suspendVMsDuringUpgrade = True
                elif l[0] == "newProductVersion":
                    newProductVersion = l[1]

        xenrt.TEC().logverbose('inputdir: %s, hosttype: %s' % (inputdir, hosttype))
        
        # Find the host to upgrade
        oldhost = xenrt.TEC().registry.hostGet(machine)
        if not oldhost:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))

        # If we supplied an inputdir we use this as a sticky override
        # for INPUTDIR
        if inputdir:
            if inputdir == "DEFAULT":
                xenrt.TEC().setInputDir(None)
            else:
                xenrt.TEC().setInputDir(inputdir)

            # Override the hosttype (Clearwater, Sanibel, etc) if a specific version has been specified
            if newProductVersion and newProductVersion != "DEFAULT":
                hosttype = newProductVersion

        # Suspend all running VMs
        suspendedVMNames = []
        if suspendVMsDuringUpgrade:
            runningVMs = filter(lambda x:x.getState() == 'UP', oldhost.guests.values())
            for vm in runningVMs:
                xenrt.TEC().logverbose('Suspending running VM %s before upgrade' % (vm.getName()))
                vm.changeCD(None)
                vm.suspend()
                suspendedVMNames.append(vm.getName())

        # Perform the upgrade. This also upgrades and replaces the host object
        host = oldhost.upgrade(hosttype)
        self.getLogsFrom(host)

        # Upgrade each of this host's guest objects
        for oldg in host.guests.values():
            g = host.guestFactory()(oldg.getName())
            oldg.populateSubclass(g)
            g.host = host
            host.guests[g.getName()] = g
            xenrt.TEC().registry.guestPut(g.getName(), g)

        if suspendVMsDuringUpgrade:
            # Check all suspended VMs are still suspended
            suspendedVMs = filter(lambda x:x.getState() == 'SUSPENDED', host.guests.values())
            for vmName in suspendedVMNames:
                newVMList = filter(lambda x:x.getName() == vmName, suspendedVMs)
                if len(newVMList) == 0:
                    raise xenrt.XRTFailure('VM no longer suspended after upgrade')
                elif len(newVMList) > 1:
                    xenrt.TEC().warning('Found %d VMs with name: %s - TEST MIGHT GIVE INVALID RESULT')
        
                xenrt.TEC().logverbose('Resuming VM %s after upgrade' % (newVMList[0].getName()))
                newVMList[0].resume()

        # Check that hosts are listed in vm-list
        guests = host.listGuests()
        missing = []
        for g in host.guests.values():
            if not g.getName() in guests:
                missing.append(g)
        if len(missing) > 0:
            xenrt.TEC().comment("Expected VMs %s" %
                                (string.join([g.getName()
                                              for g in host.guests.values()],
                                             ",")))
            xenrt.TEC().comment("Found VMs %s" %
                                (string.join([g.getName() for g in missing],
                                             ",")))
            raise xenrt.XRTFailure("%u VM(s) missing after upgrade" %
                                   (len(missing)))
       
        # Check VDIs.
        if hosttype == "Rio":
            xenrt.TEC().logverbose("Checking VDI UUIDs.")
            for uuid in host.minimalList("vdi-list"):
                if not re.match("[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}",
                                 uuid):
                    xenrt.TEC().warning("Found VDI with bad UUID(%s)." % (uuid))

        if upgradeguest:
            # Upgrade guest agents.
            xenrt.TEC().logverbose("Updating guests: %s" % ([h.getName() for h in host.guests.values()]))
            for g in host.guests.values():
                self.guest = g
                self.declareTestcase("UpgradeGuest", g.getName())
                self.runSubcase("upgradeGuest", (), "UpgradeGuest", g.getName())

    def upgradeGuest(self):
        xenrt.TEC().logverbose("Updating %s." % (self.guest.getName()))
        if self.guest.getState() == "DOWN":
            self.guest.start()
        if self.guest.windows:
            self.guest.installDrivers()  
        else:
            self.guest.installTools()
        self.guest.shutdown()

class TCXenServerSetupISOImportNFS(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCXenServerSetupISOImportNFS")
        self.blocker = True

    def run(self, arglist=None):

        if xenrt.TEC().lookup(["CLIOPTIONS", "NOPREPARE"], False,
                              boolean=True):
            xenrt.TEC().skip("Skipping because of --noprepare option")
            return

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        devices = [xenrt.TEC().lookup("EXPORT_ISO_NFS")]
        device = xenrt.TEC().lookup("EXPORT_ISO_NFS_STATIC", None)
        if device:
            devices.append(device)

        for device in devices:
            # If we have a build with
            if host.execdom0("test -e /opt/xensource/bin/xe-mount-iso-sr",
                             retval="code") == 0:
                xenrt.TEC().comment("Using xe-mount-iso-sr to mount ISOs")
                host.createISOSR(device)            
                continue

            # Skip if the mountpoint does not exist
            if host.execdom0("test -d /var/opt/xen/iso_import",
                             retval="code") != 0:
                xenrt.TEC().skip("Product does not use "
                                 "/var/opt/xen/iso_import")
        
            host.mountImports("iso", device, fstab=True)
            
            time.sleep(60)

            # This method supports only one device
            break

class TCXenServerSetupXGTImportNFS(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCXenServerSetupXGTImportNFS")

    def run(self, arglist=None):

        if xenrt.TEC().lookup(["CLIOPTIONS", "NOPREPARE"], False,
                              boolean=True):
            xenrt.TEC().skip("Skipping because of --noprepare option")
            return

        if xenrt.TEC().lookup("CARBON_BRANCH", "") == "rio-alpha":
            xenrt.TEC().skip("Skipping for rio-alpha branch")
            return

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Skip if the mountpoint does not exist
        if host.execdom0("test -d /var/opt/xen/xgt_import",
                         retval="code") != 0:
            xenrt.TEC().skip("Product does not use /var/opt/xen/xgt_import")

        device = xenrt.TEC().lookup("EXPORT_XGT_NFS")
        host.mountImports("xgt", device, fstab=True)
        time.sleep(60)

class TCGetResources(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCGetResources")

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        memory = host.getFreeMemory()
        cpus = host.getCPUCores() 
        
        nics = []
        data = host.execdom0("ifconfig").strip()
        data = data.split("\n\n")
        for i in data:
            match = re.match("eth[0-9\.]+", i)
            if match:
                iface = match.group()
                recv = re.search("RX packets:([0-9]+)", i).group(1)
                if int(recv) > 0:
                    nics.append(iface)

        path = "/xenrt/resources/%s" % (host.machine) 
        xenrt.TEC().registry.write("%s/memory" % (path), 
                                    memory)
        xenrt.TEC().registry.write("%s/cpus" % (path), 
                                    cpus)
        xenrt.TEC().registry.write("%s/nics" % (path), 
                                    nics)

        xenrt.TEC().comment("Found %sMB of free memory." % (memory))
        xenrt.TEC().comment("Found %s CPUs." % (cpus))
        xenrt.TEC().comment("Found %s NICs. (%s)" % (len(nics), nics))

class TCSubmitHCLData(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCSubmitHCLData")

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        host.submitToHCL() 

class TCHostReboot(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCHostReboot")
        self.guests = []
        self.host = None

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        guests = 3
        stayup = 2

        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." % (machine))
        self.getLogsFrom(host)

        # Install Debian guests.
        xenrt.TEC().logverbose("Installing %s guests." % (guests))
        for i in range(guests):
            g = self.host.createGenericLinuxGuest(name="debian-%s" % (i))
            g.check()
            xenrt.TEC().registry.guestPut("debian-%s" % (i), g)
            self.guests.append(g)
            self.getLogsFrom(g)

        # Set two VMs to auto power on.     
        for i in range(stayup):
            self.guests[i].paramSet("other-config-auto_poweron", "true")

        # Make a note of last time the guests were shutdown.
        shutdownTimes = []
        for i in range(guests):
            shutdownTimes.append(self.guests[i].getLastShutdownTime())

        # Reboot host.
        xenrt.TEC().logverbose("Rebooting host.")
        host.reboot()
        host.waitForSSH(300)
        time.sleep(30)

        for i in range(stayup):
            if not self.guests[i].getState() == "UP":
                raise xenrt.XRTFailure("Guest %s did not auto power on." % 
                                       (self.guests[i].getName()))
            else:
                xenrt.TEC().logverbose("Found %s in the UP state." % 
                                       (self.guests[i].getName()))
        for i in range(stayup, guests):
            if not self.guests[i].getState() == "DOWN":
                raise xenrt.XRTFailure("Guest %s auto powered on." % 
                                       (self.guests[i].getName()))
            else:
                xenrt.TEC().logverbose("Found %s in the DOWN state." % 
                                       (self.guests[i].getName()))
            # Start the shutdown guest as well.
            self.guests[i].start()
            self.guests[i].waitForSSH(300)

        # Check for clean shutdown.
        xenrt.TEC().logverbose("Checking guests shutdown cleanly.")
        for i in range(guests):
            if shutdownTimes[i]:
                if not self.guests[i].getLastShutdownTime() > shutdownTimes[i]:
                    raise xenrt.XRTFailure("Guest %s does not appear to have "
                                           "shutdown cleanly." % 
                                           (self.guests[i].getName()))
            else:   
                if not self.guests[i].getLastShutdownTime():
                    raise xenrt.XRTFailure("Guest %s does not appear to have "
                                           "shutdown cleanly." % 
                                           (self.guests[i].getName()))


    def postRun(self):
        for g in self.guests:
            try:
                g.shutdown()
            except:
                pass
            try:
                g.uninstall()
            except:
                pass

class TCWatchdog(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCWatchdog")

    def run(self, arglist=None):
        
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." % (machine))
        self.getLogsFrom(host)

        kap = int(xenrt.TEC().lookup("WATCHDOG_KEEP_ALIVE_PERIOD", "15"))

        if not host.execcmd("ls /opt/xensource/libexec/watchdogd"):
            xenrt.TEC().skip("No watchdogd found.")
            return

        lastboot = host.getLastBootTime()
        xenrt.TEC().logverbose("Last boot time was at: %s" % (lastboot))

        # Wait for more than the timeout and check we haven't rebooted.
        xenrt.TEC().logverbose("Waiting for 150% of keep alive period and checking "
                               "we haven't rebooted in the meantime.")
        time.sleep((kap * 3)/2)
        if not lastboot == host.getLastBootTime():
            raise xenrt.XRTFailure("Host rebooted at %s during "
                                   "normal operation." % (lastboot))

        # Disable the watchdog and make sure the host doesn't reboot.
        xenrt.TEC().logverbose("Disabling the watchdog service.")
        host.execcmd("service xen-watchdog stop")
        xenrt.TEC().logverbose("Waiting for 150% of keep alive period and checking "
                               "we haven't rebooted in the meantime.")
        time.sleep((kap * 3)/2)
        if not lastboot == host.getLastBootTime():
            raise xenrt.XRTFailure("Host rebooted at %s after "
                                   "stopping watchdog service." % (lastboot))

        # Start the watchdog again and check the host doesn't reboot.
        xenrt.TEC().logverbose("Enabling the watchdog service.")
        host.execcmd("service xen-watchdog start")
        xenrt.TEC().logverbose("Waiting for 150% of keep alive period and checking "
                               "we haven't rebooted in the meantime.")
        time.sleep((kap * 3)/2)
        if not lastboot == host.getLastBootTime():
            raise xenrt.XRTFailure("Host rebooted at %s after "
                                   "starting watchdog service." % (lastboot))

        # Restart the watchdog and check the host doesn't reboot.
        xenrt.TEC().logverbose("Restarting the watchdog service.")
        host.execcmd("service xen-watchdog restart")
        xenrt.TEC().logverbose("Waiting for 150% of keep alive period and checking "
                               "we haven't rebooted in the meantime.")
        time.sleep((kap * 3)/2)
        if not lastboot == host.getLastBootTime():
            raise xenrt.XRTFailure("Host rebooted at %s after "
                                   "restarting watchdog service." % (lastboot))

        # Kill the watchdog and check the host reboots.
        pid = host.execcmd("ps -C \"watchdogd\" -o pid=").strip()
        xenrt.TEC().logverbose("Watchdog PID: %s" % (pid))
        xenrt.TEC().logverbose("Killing the watchdog service.")
        host.execcmd("kill -9 %s" % (pid))
        time.sleep((kap * 3))
        host.waitForSSH(180)
        recentboot = host.getLastBootTime()
        if not recentboot > lastboot:
            raise xenrt.XRTFailure("Host didn't reboot after "
                                   "watchdog service died.")
        xenrt.TEC().logverbose("Rebooted at %s." % (recentboot))

class TCCreatePool(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCCreatePool")
        self.blocker = True

    def run(self, arglist=None):

        if not arglist or len(arglist) < 2:
            raise xenrt.XRTError("Need at least a master and a pool name.")
        poolname = arglist[0]
        mastername = arglist[1]
        force = xenrt.TEC().lookup("POOL_JOIN_FORCE", False, boolean=True)

        host = xenrt.TEC().registry.hostGet(mastername)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." %
                                 (mastername))
        self.getLogsFrom(host)

        # Create the pool object with the master host.
        pool = xenrt.lib.xenserver.poolFactory(host.productVersion)(host)

        # Set the crashdump and suspend default SRs to be the shared
        # storage.
        if not xenrt.TEC().lookup("POOL_NO_DEFAULT_SR", False, boolean=True):
            sruuid = pool.master.parseListForUUID("sr-list",
                                                  "name-label",
                                                   pool.master.defaultsr)
            pool.setPoolParam("default-SR", sruuid)
            pool.setPoolParam("crash-dump-SR", sruuid)
            pool.setPoolParam("suspend-image-SR", sruuid)
        else:
            # This is really to work around an annoying OEM trait...
            pool.clearPoolParam("crash-dump-SR")
            pool.clearPoolParam("suspend-image-SR")
        pool.setPoolParam("name-label", poolname)

        if xenrt.TEC().lookup("POOL_SHARED_DB", False, boolean=True):
            # Use shared DB on this pool          
            pool.setupSharedDB()

        for arg in arglist:
            if arg == "joinall":
                hostlist = xenrt.TEC().registry.hostList()
                hostlist.remove(mastername)
                break
            else:
                hostlist = arglist[2:]

        # Add other hosts to this pool.
        for slavename in hostlist:
            slave = xenrt.TEC().registry.hostGet(slavename)
            if not slave:
                raise xenrt.XRTError("Unable to find host %s in registry." %
                                     (slavename))
            self.getLogsFrom(slave)
            pool.addHost(slave, force=force)
            # Optionally create a NFS server running from the host
            if xenrt.TEC().lookup("OPTION_LOCAL_NFS", False, boolean=True):
                slave.makeLocalNFSSR()

        pool.check()
        xenrt.TEC().registry.poolPut(poolname, pool)

class TCDumpRestorePoolDB(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCDumpRestorePoolDB")

    def run(self, arglist=None):

        pool = None
        poolname = None

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "poolname":
                poolname = l[1]
        
        if not poolname:
            raise xenrt.XRTError("Need to specify a pool name.")

        pool = xenrt.TEC().registry.poolGet(poolname)
        if not pool:
            raise xenrt.XRTError("Could not find pool %s in registry." %
                                 (poolname))

        self.getLogsFrom(pool.master)
        
        tmpfile = xenrt.TEC().tempFile()
        xenrt.command("rm -f %s" % (tmpfile))

        pool.dump(tmpfile)
        pool.restore(tmpfile)
        pool.check()

class TCAddHostToPool(xenrt.TestCase):
        
    def __init__(self):
        xenrt.TestCase.__init__(self, "TCAddHostToPool")
        
    def run(self, arglist=None):

        pool = None
        poolname = None
        hosts = None
        expectfail = False

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "poolname":
                poolname = l[1]
            elif l[0] == "expectfail":
                expectfail = True
            elif l[0] == "hosts":
                hosts = string.split(l[1], ",")

        if not poolname:
            raise xenrt.XRTError("Need to specify a pool name.")
        
        force = xenrt.TEC().lookup("POOL_JOIN_FORCE", False, boolean=True)

        pool = xenrt.TEC().registry.poolGet(poolname)
        if not pool:
            raise xenrt.XRTError("Could not find pool %s in registry." %
                                 (poolname))

        for slave in hosts:
            shost = xenrt.TEC().registry.hostGet(slave)
            if not shost:
                raise xenrt.XRTError("Unable to find host %s in registry." %
                                     (slave))
            self.getLogsFrom(shost)
            try:
                pool.addHost(shost, force=force)
            except Exception, e:
                if expectfail:
                    pool.check()
                    continue 
                else:
                    raise xenrt.XRTFailure("Failed to add host %s to pool." % (slave))

            if expectfail:
                raise xenrt.XRTFailure("Added host %s to pool." % (slave))

            pool.check()

class TCRemoveHostFromPool(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCRemoveHostFromPool")

    def run(self, arglist=None):
    
        poolname = None
        hosts = None
        crash = False
        restart = False
        known = True

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "poolname":
                poolname = l[1]
            elif l[0] == "hosts":
                hosts = string.split(l[1], ",")
            elif l[0] == "crash":
                crash = True
            elif l[0] == "restart":
                restart = True
            elif l[0] == "unknown":
                known = False
        
        if not poolname:
            raise xenrt.XRTError("A pool name must be specified.")
        pool =  xenrt.TEC().registry.poolGet(poolname)
        if not pool:
            raise xenrt.XRTError("Could not find pool %s in registry." %
                                 (poolname))
            
        for h in hosts:
            host = xenrt.TEC().registry.hostGet(h)
            if not host:
                raise xenrt.XRTError("Unable to find host %s in registry." %
                                     (h))
            self.getLogsFrom(host)
            if crash:
                host.execdom0("/etc/init.d/xapi stop")
                time.sleep(60)
                host.pool = None
                if known:
                    pool.forget(host)
                time.sleep(30)
                # Sort out state on 'crashed' host.
                host.execdom0("rm -f /var/xapi/state.db")
                host.execdom0("rm -f /etc/xensource/pool.conf")
                host.execdom0("echo master > /etc/xensource/pool.conf")
                host.startXapi()
                host.defaultsr = None
                host.execdom0("dmsetup remove_all")
                host.execdom0("sh /var/xapi/firstboot-SR-commands.completed",
                               level=xenrt.RC_OK)
            elif restart:
                host.execdom0("/etc/init.d/xapi stop")
                time.sleep(120)
                host.startXapi()
            else:
                pool.eject(host)
        
        pool.check()

class TCChangePoolMaster(xenrt.TestCase):  

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCChangePoolMaster")

    def checkEmergency(self, pool):
        for slave in pool.slaves.values():
            cli = slave.getCLIInstance(local=True)
            emode = None
            try:
                emode = cli.execute("host-is-in-emergency-mode")
            except:
                # Use legacy method
                data = cli.execute("host-list", ignoreerrors=True)
                if not re.search("emergency", data):
                    if re.search("The host is still booting", data):
                        xenrt.TEC().warning("Using emergency mode check "
                                            "workaround")
                    else:
                        raise xenrt.XRTFailure("Host %s isn't in emergency "
                                               "mode." % (slave.getName()))
            if emode:
                if not re.search("true", emode):
                    raise xenrt.XRTFailure("Host %s isn't in emergency mode." %
                                           (slave.getName()))

    def run(self, arglist=None):
        
        poolname = None
        master = None
        crash = False
        restart = False
        loops = 1
        mix = False

        retries = 2

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "poolname":
                poolname = l[1]
            elif l[0] == "master":
                master = l[1]
            elif l[0] == "crash":
                crash = True
            elif l[0] == "restart":
                restart = True
            elif l[0] == "mix":
                mix = True
 
        if not poolname:
            raise xenrt.XRTError("A pool name must be specified.")
        pool =  xenrt.TEC().registry.poolGet(poolname)
        if not pool:
            raise xenrt.XRTError("Could not find pool %s in registry." %
                                 (poolname))
        if master:
            m = xenrt.TEC().registry.hostGet(master)
            if not m:
                raise xenrt.XRTError("Unable to find host %s in registry." %
                                     (master))
        self.getLogsFrom(pool.master)

        if mix:
            option = random.randint(0,2)
            if option == 0:
                crash = False
                restart = False
            elif option == 1:
                crash = True
                restart = False
            elif option == 2:
                crash = False
                restart = True        
        if crash:
            if not m:
                raise xenrt.XRTError("Must specify new master.")
            oldmaster = pool.master
            pool.master.execdom0("/etc/init.d/xapi stop")
            time.sleep(300)
            self.checkEmergency(pool)
            pool.setMaster(m)
            pool.forget(oldmaster)
            for i in range(retries):
                pool.recoverSlaves()
                actual = pool.listSlaves()
                actual.sort()
                slaves = pool.slaves.keys()
                slaves.sort()
                xenrt.TEC().logverbose("Looking for: %s" % (slaves))
                xenrt.TEC().logverbose("Found: %s" % (actual))
                if slaves == actual:
                    break
                if i == retries - 1:
                    raise xenrt.XRTFailure("Couldn't recover all slaves.")
                time.sleep(30)
            # Sort out state on 'crashed' host.
            oldmaster.execdom0("rm -f /var/xapi/state.db")
            oldmaster.execdom0("rm -f /etc/xensource/pool.conf")
            oldmaster.execdom0("echo master > /etc/xensource/pool.conf")
            oldmaster.startXapi()
            oldmaster.defaultsr = None
            oldmaster.execdom0("dmsetup remove_all")
            oldmaster.execdom0("sh /var/xapi/firstboot-SR-commands.completed",
                                level=xenrt.RC_OK)
        elif restart:
            pool.master.execdom0("/etc/init.d/xapi stop")
            time.sleep(300)
            self.checkEmergency(pool)
            pool.master.startXapi()
            time.sleep(300)
        else:
            if not m:
                raise xenrt.XRTError("Must specify new master.")
            oldmaster = pool.master
            oldmaster.execdom0("/etc/init.d/xapi stop")
            time.sleep(300)
            self.checkEmergency(pool)
            pool.setMaster(m)
            oldmaster.startXapi()
            for i in range(retries):
                pool.recoverSlaves()
                actual = pool.listSlaves()
                actual.sort()
                slaves = pool.slaves.keys()
                slaves.sort()
                xenrt.TEC().logverbose("Looking for: %s" % (slaves))
                xenrt.TEC().logverbose("Found: %s" % (actual))
                if slaves == actual:
                    break
                if i == retries - 1:
                    raise xenrt.XRTFailure("Couldn't recover all slaves.")
                time.sleep(30)
        
        pool.check()

class SourceISOCheck(xenrt.TestCase):
    """Base class for verifying for missing RPMs."""

    APPLIANCE_NAME = None # the appliance VM under test.
    IGNORE_RPM_VERSION = "no" # if yes, ignored rpm version numbers from comparision.

    SOURCE_RPM_PACKAGES = [] # list of rpms in the source ISOs
    INSTALLED_RPM_PACKAGES = [] # list of rpms in the installed appliance.
    SOURCE_ISO_FILES = {} # {'iso-file': 'path'} dictionary of source iso files.

    # list of base rpm packages to be ignored from comparision.
    IGNORE_BASE_RPM_PACKAGES = [
                        'likewise-open-domainjoin', 
                        'likewise-open-eventlog', 
                        'likewise-open-libs', 
                        'likewise-open-lsass', 
                        'likewise-open-lwio', 
                        'likewise-open-lwreg', 
                        'likewise-open-lwsm', 
                        'likewise-open-netlogon', 
                        'likewise-open-rpc', 
                        'likewise-open-srvsvc',
                        'pbis-open',
                        'pbis-open-upgrade'
                        ]

    # list of extra rpm packages to be ignored from comparision.
    IGNORE_EXTRA_RPM_PACKAGES = []

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        for arg in arglist:
            if arg.startswith('ignorerpmversion'):
                self.IGNORE_RPM_VERSION = arg.split('=')[1]

    def removeRpmVersion(self, rpmList):
        """Removes the rpm package version"""

        temp=[]
        noVersion=[]
        for i in range(len(rpmList)):
            for j in range(len(rpmList[i])):
                if (rpmList[i][j] == "_" or rpmList[i][j] == "-")and rpmList[i][j+1].isdigit():
                    break
                temp.append(rpmList[i][j])
            noVersion.append(''.join(temp))
            temp = []
        return noVersion

    def revertRpmVersion(self, diffRpmList, diffRpmListNoVersion):
        """Reverts the rpm package version to original"""

        diffRpmListWithVersion = []
        for i in range(len(diffRpmListNoVersion)):
            for j in range(len(diffRpmList)):
                if(diffRpmList[j].startswith(diffRpmListNoVersion[i])) and (diffRpmList[j][len(diffRpmListNoVersion[i])+1].isdigit()):
                    diffRpmListWithVersion.append(diffRpmList[j])
        return diffRpmListWithVersion

    def setInstalledRpmPackages(self, installedRpmList):
        """Obtain a list of installed rpm packages from the appliance."""

        if not installedRpmList:
            raise xenrt.XRTFailure("Unable to obtain the list of rpm packages from %s appliance." %
                                                                                    self.APPLIANCE_NAME)
        installedRpmList = installedRpmList.splitlines()
        installedRpmList.sort()
        self.INSTALLED_RPM_PACKAGES = installedRpmList

        xenrt.TEC().logverbose("The list of installed rpm packages in %s appliance are \n%s " %
                            (self.APPLIANCE_NAME, "\n".join(map(str, self.INSTALLED_RPM_PACKAGES))))

    def setSourceRpmPackages(self):
        """Obtains a list of rpms provided in the source files"""

        sourceRpmPackageList = []
        
        for sourceFile, sourceBuildPath in self.SOURCE_ISO_FILES.iteritems():
            try:
                # e.g download xe-phase-3/source-1.iso and list the RPMs.
                file = xenrt.TEC().getFile(sourceBuildPath+"/"+sourceFile, sourceFile)
                if file:                
                    if sourceFile.endswith(".iso"):
                        mount = xenrt.MountISO(file)
                        mountpoint = mount.getMount()
                    else:
                        mountpoint = xenrt.TEC().tempDir()
                        xenrt.util.command("tar -xvf %s -C %s" % (file, mountpoint))

                    if self.APPLIANCE_NAME == "DVSC Controller VM":
                        # Retrieve all the package file names with .dsc extension.
                        tmp_list = xenrt.recursiveFileSearch(mountpoint, "*.dsc")
                        tmpSourceRpmPackageList = [os.path.splitext(filename)[0] for filename in tmp_list]
                        
                    else:
                        tmpSourceRpmPackageList = xenrt.recursiveFileSearch(mountpoint, "*.src.rpm")

                    if not tmpSourceRpmPackageList:
                        raise xenrt.XRTFailure("Unable to obtain the list of rpm packages from %s/%s for %s." %
                                                            (sourceBuildPath, sourceFile, self.APPLIANCE_NAME))
                                           
                    # To obtain merged list of unique RPMs.
                    sourceRpmPackageList = sourceRpmPackageList + tmpSourceRpmPackageList
                    
            finally:
                try:
                    if file:
                        mount.unmount()
                except:
                    pass
        if not sourceRpmPackageList:
            raise xenrt.XRTFailure("Unable to obtain any source ISOs for %s (%s)." % (self.APPLIANCE_NAME, self.host.productVersion))
        sourceRpmPackageList.sort()
        self.SOURCE_RPM_PACKAGES = sourceRpmPackageList

        xenrt.TEC().logverbose("The list of source rpm packages available in %s source ISO are \n%s " %
                                    (self.APPLIANCE_NAME, "\n".join(map(str, self.SOURCE_RPM_PACKAGES))))

    def ignoreRpmPackagesFromComparison(self):
        """Ignores the specified packages from comparision"""

        # To obtain a merged list of RPMs to ignore.
        ignoreRpmPackages = self.IGNORE_BASE_RPM_PACKAGES + self.IGNORE_EXTRA_RPM_PACKAGES

        ignoredRpmList = []
        for package in ignoreRpmPackages:
            ignoredRpmList = ignoredRpmList + filter(lambda rpm: rpm.startswith(package), self.INSTALLED_RPM_PACKAGES)

        # Get rpms in self.INSTALLED_RPM_PACKAGES, but not in ignoredRpmList.
        self.INSTALLED_RPM_PACKAGES = list(set(self.INSTALLED_RPM_PACKAGES) - set(ignoredRpmList))
        if ignoredRpmList:
            xenrt.TEC().logverbose("The following RPM packages in %s are not considered for comparision \n%s " %
                                                        (self.APPLIANCE_NAME, "\n".join(map(str, ignoredRpmList))))
        else:
            xenrt.TEC().logverbose("No rpm packages in %s appliance are excluded from comparision." %
                                                                                    self.APPLIANCE_NAME)

    def compareRpmPackages(self):
        """Comapring installed RPM against the source RPMS"""

        # Get rpms in SOURCE_RPM_PACKAGES, but not in INSTALLED_RPM_PACKAGES.
        diffSourceRpmList = list(set(self.SOURCE_RPM_PACKAGES) - set(self.INSTALLED_RPM_PACKAGES))
        diffSourceRpmList.sort()

        if diffSourceRpmList:
            xenrt.TEC().logverbose("The additional rpm packages in %s source ISO are \n%s " %
                                    (self.APPLIANCE_NAME, "\n".join(map(str, diffSourceRpmList))))
        else:
            xenrt.TEC().logverbose("There are no additional rpm packages in %s source ISO." %
                                                                            self.APPLIANCE_NAME)

        # Get rpms in INSTALLED_RPM_PACKAGES, but not in SOURCE_RPM_PACKAGES.
        diffInstalledRpmList = list(set(self.INSTALLED_RPM_PACKAGES) - set(self.SOURCE_RPM_PACKAGES))
        diffInstalledRpmList.sort()

        if diffInstalledRpmList:
            xenrt.TEC().logverbose("The missing rpm packages in %s are \n%s " %
                            (self.APPLIANCE_NAME, "\n".join(map(str, diffInstalledRpmList))))

            # Ignore package version numbers while comparing the packages.
            if self.IGNORE_RPM_VERSION == "yes":
                xenrt.TEC().logverbose("Now ignoring the rpm package version numbers from comparisions ...")

                installedRpmListNoVersion = self.removeRpmVersion(self.INSTALLED_RPM_PACKAGES)
                sourceRpmListNoVersion = self.removeRpmVersion(self.SOURCE_RPM_PACKAGES)
                diffRpmListNoVersion = list(set(installedRpmListNoVersion) - set(sourceRpmListNoVersion))
                diffRpmListNoVersion.sort()
                
                if diffRpmListNoVersion:
                    diffRpmListWithVersion = self.revertRpmVersion(self.INSTALLED_RPM_PACKAGES, diffRpmListNoVersion )
                    diffRpmListWithVersion.sort()
                    xenrt.TEC().logverbose("The missing rpm packages in %s  after ignoring package version number are \n%s " %
                                                            (self.APPLIANCE_NAME, "\n".join(map(str, diffRpmListWithVersion))))
                                            
                    raise xenrt.XRTFailure("There are missing rpm packages in %s appliance (%s)." % (self.APPLIANCE_NAME, self.host.productVersion))
                else:
                    xenrt.TEC().logverbose("No missing rpm packages are found in %s appliance after ignoring the version numbers." % self.APPLIANCE_NAME)

            else: # IGNORE_RPM_VERSION == "no"
                raise xenrt.XRTFailure("There are missing rpm packages in %s appliance (%s)." % (self.APPLIANCE_NAME, self.host.productVersion))
        else:
            xenrt.TEC().logverbose("No missing rpm packages are found in %s appliance." % self.APPLIANCE_NAME)

class TCDom0SourceCheck(SourceISOCheck): # TC-17998
    """Verify dom0 source iso (xe-phase-3/source-1.iso & source-4.iso) for missing RPMs."""

    APPLIANCE_NAME = "Dom0"
    
    IGNORE_EXTRA_RPM_PACKAGES = ['libev', 'perf-tools'] # in addition to the list of base packages.
                                                        # perf-tools missing from tampa onwards

    def prepare(self, arglist=None):
        self.SOURCE_ISO_FILES = self.getDefaultHost().SOURCE_ISO_FILES
        SourceISOCheck.prepare(self, arglist)
    
    def run(self, arglist=None):
        
        versiontype = xenrt.TEC().lookup("PRODUCT_VERSION")
        
        patches = xenrt.TEC().lookupLeaves("CARBON_PATCHES_%s" % string.upper(versiontype))        
        if len(patches) == 1:
            patches = string.split(patches[0], ",")
        cpatches = xenrt.TEC().lookupLeaves("CPATCHES_%s" % string.upper(versiontype)) 
        if len(cpatches) == 1:
            cpatches =  string.split(cpatches[0], ",")
        patches.extend(cpatches)
        
        if len(patches) >= 1:
            for i in patches:
                hotfixDirectory = os.path.split(i)
                filename =  hotfixDirectory[0].split("hotfix-")[-1]
                self.SOURCE_ISO_FILES[filename+'-src-pkgs.tar']= hotfixDirectory[0]
            
        # This list inlcudes rpm's installed in Dom0. (which is distributed in source-1.iso & source-4.iso)
        installedRpmList = self.host.execdom0("for r in `rpm -qa`; "
            "do gpl=`rpm -q --qf %{License} $r|grep -ci \"GPL\|Apache\|AFL\|Artistic\|DFSG\|MPL\"`; "
            "   if [ $gpl -ge 1 ]; then echo `rpm -q --qf %{SourceRPM} $r`; "
            "fi; done | sort | uniq")

        self.setInstalledRpmPackages(installedRpmList)

        # Download xe-phase-3/source-1.iso and xe-phase-3/source-4.iso.
        self.setSourceRpmPackages()

        self.ignoreRpmPackagesFromComparison()

        self.compareRpmPackages()

class TCDLVMSourceCheck(SourceISOCheck): # TC-17999
    """Verify Demo Linux source iso (xe-phase-3/source-dlvm.iso) for missing RPMs."""

    APPLIANCE_NAME = "Demo Linux VM"
    SOURCE_ISO_FILES = {'source-dlvm.iso': 'xe-phase-3'}

    IGNORE_BASE_RPM_PACKAGES = IGNORE_EXTRA_RPM_PACKAGES = [] # notihng to ignore as base+extra packages.

    def prepare(self, arglist=None):
        # Calling base class prepare first.
        SourceISOCheck.prepare(self, arglist)

        # Installing DVLM appliance.
        g = self.host.guestFactory()(\
            self.APPLIANCE_NAME, "NO_TEMPLATE",
            password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        xenrt.TEC().registry.guestPut(self.APPLIANCE_NAME, g)
        g.host = self.host
        self.demolinuxvm = xenrt.DemoLinuxVM(g)
        g.importVM(self.host, xenrt.TEC().getFile("xe-phase-1/dlvm.xva"))
        g.windows = False
        g.lifecycleOperation("vm-start",specifyOn=True)
        # Wait for the VM to come up.
        xenrt.TEC().progress("Waiting for the VM to enter the UP state")
        g.poll("UP", pollperiod=5)
        # Wait VM to boot up
        time.sleep(300)
        self.demolinuxvm.doFirstbootUnattendedSetup()
        self.demolinuxvm.doLogin()
        self.demolinuxvm.installSSH()
        g.hasSSH = True
        time.sleep(30)
        # restart and see if the demo linux services are up
        g.shutdown()
        g.start()
        time.sleep(60)
        return g

    def run(self, arglist=None):

        demoLinuxVM = self.host.getGuest(self.APPLIANCE_NAME)
        installedRpmList = demoLinuxVM.execcmd("for r in `rpm -qa`; "
            "do gpl=`rpm -q --qf %{License} $r|grep -ci \"GPL\|Apache\|AFL\|Artistic\|DFSG\|MPL\"`; "
            "   if [ $gpl -ge 1 ]; then echo `rpm -q --qf %{SourceRPM} $r`; "
            "fi; done | sort | uniq")

        self.setInstalledRpmPackages(installedRpmList)

        # Download xe-phase-3/source-dlvm.iso
        self.setSourceRpmPackages()

        self.ignoreRpmPackagesFromComparison()

        self.compareRpmPackages()

class TCVPXWLBSourceCheck(SourceISOCheck): # TC-18000
    """Verifiy WLB Virtual Appliance source iso (xe-phase-3/source-wlb.iso) for missing RPMs."""

    APPLIANCE_NAME = "VPX WLB VM"
    SOURCE_ISO_FILES = {'source-wlb.iso': 'xe-phase-3'}
    IGNORE_BASE_RPM_PACKAGES = IGNORE_EXTRA_RPM_PACKAGES = [] # notihng to ignore as base+extra packages.

    def prepare(self, arglist=None):
        # Calling base class prepare first.
        SourceISOCheck.prepare(self, arglist)

        # Installing WLB Appliance VM
        self.distro = "wlbapp"
        self.wlbserver = None
        self.wlbserver_name = self.APPLIANCE_NAME
        self.vpx_os_version = xenrt.TEC().lookup("VPX_OS_VERSION", "CentOS5")
        g = self.host.guestFactory()(\
            self.wlbserver_name, "NO_TEMPLATE",
            password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        xenrt.TEC().registry.guestPut(self.APPLIANCE_NAME, g)
        g.host = self.host
        self.wlbserver = xenrt.WlbApplianceFactory().create(g, self.vpx_os_version)
        g.importVM(self.host, xenrt.TEC().getFile("xe-phase-1/vpx-wlb.xva"))
        g.windows = False
        g.hasSSH = False # here we should support both old (CentOS5) and new (CentOS7) WLB, disable sshcheck
        g.tailored = True # We do not need tailor for WLB, and old (CentOS5) WLB does not have ssh.
        g.start()
        self.getLogsFrom(g)

        self.wlbserver.doFirstbootUnattendedSetup()
        self.wlbserver.doLogin()
        self.wlbserver.doSanityChecks()
        self.wlbserver.installSSH()
        g.hasSSH = True
        time.sleep(30)
        # restart and see if the wlb services are still up
        g.shutdown()
        g.start()
        time.sleep(60)
        self.wlbserver.doLogin()
        self.wlbserver.doSanityChecks()
        return g

    def run(self, arglist=None):

        wlbserverVM = self.host.getGuest(self.APPLIANCE_NAME)
        installedRpmList = wlbserverVM.execcmd("for r in `rpm -qa`; "
            "do gpl=`rpm -q --qf %{License} $r|grep -ci \"GPL\|Apache\|AFL\|Artistic\|DFSG\|MPL\"`; "
            "   if [ $gpl -ge 1 ]; then echo `rpm -q --qf %{SourceRPM} $r`; "
            "fi; done | sort | uniq")

        self.setInstalledRpmPackages(installedRpmList)

        self.ignoreRpmPackagesFromComparison()

        # Download xe-phase-3/source-wlb.iso
        self.setSourceRpmPackages()

        self.compareRpmPackages()

class TCVPXConversionSourceCheck(SourceISOCheck): # TC-18001
    """Verifiy XCM Virtual Appliance source iso (xe-phase-3/source-conversion.iso) for missing RPMs."""

    APPLIANCE_NAME = "VPX Conversion VM"
    SOURCE_ISO_FILES = {'source-conversion.iso': 'xe-phase-3'}

    IGNORE_BASE_RPM_PACKAGES = [] # nothing to ignore as base packages.
    IGNORE_EXTRA_RPM_PACKAGES = ['texinfo', 'xe-guest-utilities']

    def prepare(self, arglist=None):
        # Calling base class prepare first.
        SourceISOCheck.prepare(self, arglist)

        self.convServerName = self.APPLIANCE_NAME
        self.vpx_os_version = xenrt.TEC().lookup("VPX_OS_VERSION", "CentOS5")
        self.host = self.getDefaultHost()

        g = self.host.guestFactory()(\
            self.convServerName, "NO_TEMPLATE",
            password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))

        xenrt.TEC().registry.guestPut(self.convServerName, g)
        g.host = self.host

        # Import VPX
        self.convServer = xenrt.ConversionManagerApplianceFactory().create(g, self.vpx_os_version)
        xenrt.TEC().logverbose("Importing Conversion VPX")
        g.importVM(self.host, xenrt.TEC().getFile("xe-phase-1/vpx-conversion.xva"))
        xenrt.TEC().logverbose("Conversion VPX Imported")
        g.windows = False
        g.hasSSH = False # here we should support both old (CentOS5) and new (CentOS7) XCM, disable sshcheck
        g.tailored = True # We do not need tailor for XCM, and old (CentOS5) XCM does not have ssh.
        g.start(managebridge=g.host.getPrimaryBridge())
        self.getLogsFrom(g)

        self.convServer.doFirstbootUnattendedSetup()
        #self.convServer.doSanityChecks()
        # Increasing default uptime from 300 seconds to 3600 seconds
        self.convServer.increaseConversionVMUptime(3600)
        g.hasSSH = True
        time.sleep(30)

        # Check VPX to obtain its IP address
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        host_ref = session.xenapi.session.get_this_host(session.handle)
        args = {}
        vpx_ip = session.xenapi.host.call_plugin(host_ref, 'conversion', 'main', args)
        xenrt.TEC().logverbose("ConversionVM::VPX IP = %s" % vpx_ip)

        # Set the main IP Address of the VPX Conversion guest object, if not set.
        if not g.mainip:
            g.mainip=vpx_ip

        # restart the conversion vm so that we can ssh
        if g.getState() == "UP":
            g.lifecycleOperation("vm-shutdown")
        if g.getState() != "UP":
            g.lifecycleOperation("vm-start",specifyOn=True)
        time.sleep(60)
        self.convServer.doLogin()
        #self.convServer.doSanityChecks()
        return g

    def run(self, arglist=None):

        xcmVirtualApplianceVM = self.host.getGuest(self.APPLIANCE_NAME)
        wlbserverVM = self.host.getGuest(self.APPLIANCE_NAME)
        
        installedRpmList = wlbserverVM.execcmd("for r in `rpm -qa`; "
            "do gpl=`rpm -q --qf %{License} $r|grep -ci \"GPL\|Apache\|AFL\|Artistic\|DFSG\|MPL\"`; "
            "   if [ $gpl -ge 1 ]; then echo `rpm -q --qf %{SourceRPM} $r`; "
            "fi; done | sort | uniq")

        self.setInstalledRpmPackages(installedRpmList)

        self.ignoreRpmPackagesFromComparison()

        # Download xe-phase-3/source-conversion.iso
        self.setSourceRpmPackages()

        self.compareRpmPackages()

class TCDVSControllerSourceCheck(SourceISOCheck): # TC-18002
    """Verifiy DVS Controller 13878 amd64 source iso (xe-phase-3/source-dvsc.iso) for missing deb packages."""

    APPLIANCE_NAME = "DVSC Controller VM"
    SOURCE_ISO_FILES = {'source-dvsc.iso': 'xe-phase-3'}

    IGNORE_BASE_RPM_PACKAGES = ['openvswitch'] # missing from tampa onwards.
    IGNORE_EXTRA_RPM_PACKAGES = ['nox_6'] # package nox_6.1.0.15430 is controller itself.

    def formatPackagesForComparison(self):
        """Format the DVSC packages as required by the test"""

        formatedPackageList = []

        # Example:- libgcc1*gcc-4.3 (4.3.2-1.1)*1:4.3.2-1.1+b1 corresponds to (packageName, sourceName, versionNumber)
        for line in self.INSTALLED_RPM_PACKAGES:
            packageName, sourceName, versionNumber = line.split("*")

            # 1.) For sourceName, remove whatever in bracket. [in the example above remove (4.3.2-1.1)]
            if sourceName:
                sourceName = re.sub(r"\s*\([^)]*\)", '', sourceName)

            # 2.) For versionNumber, use the values after : [in the example above use 4.3.2-1.1+b1]
            if versionNumber and re.search(r":", versionNumber):
                versionNumber = versionNumber.split(":")[1]

            # 3.) Remove +b1 from versionNumber, if any. [in the example above use 4.3.2-1.1]
            if versionNumber:
                versionNumber = versionNumber.replace("+b1", "")
            
            if not sourceName:
                # 4.) If there is no sourceName, use packageName
                sourceFile = (("%s_%s") % (packageName, versionNumber))
                formatedPackageList.append(sourceFile)
            else:
                sourceFile = (("%s_%s") % (sourceName, versionNumber))
                formatedPackageList.append(sourceFile)

        self.INSTALLED_RPM_PACKAGES = formatedPackageList

    def run(self, arglist=None):

        # Install a DVSC controller
        dvscVM = self.host.getGuest(self.APPLIANCE_NAME)

        # List all packages from DVSC controller matching the given pattern/format string.
        dpkg_query = "dpkg-query -W -f='${Package}*${Source}*${Version}\n'"
        dvscRawPackageList = dvscVM.execcmd(dpkg_query, username="root", password="2R*QvK-")

        self.setInstalledRpmPackages(dvscRawPackageList)

        # Format the DVSC packages as required by the test.
        self.formatPackagesForComparison()

        self.ignoreRpmPackagesFromComparison()

        # Download xe-phase-3/source-dvsc.iso
        self.setSourceRpmPackages()

        self.compareRpmPackages()

class TCDDKSourceCheck(SourceISOCheck): # TC-18003
    """Verify DDK iso (xe-phase-3/source-ddk.iso) content for missing RPMs."""

    APPLIANCE_NAME = "DDK VM"
    SOURCE_ISO_FILES = {'source-ddk.iso': 'xe-phase-3', 'source-1.iso': 'xe-phase-3'}

    # In addition to the list of base packages, we have ...
    IGNORE_EXTRA_RPM_PACKAGES = ['PyPAM', 'SDL', 'biosdevname', 'blktap', 'dbus', 'device-mapper-multipath', 
                                'e2fsprogs', 'ethtool', 'hwdata', 'iproute', 'iptables', 'lvm2', 'mbootpack', 
                                'mercurial', 'mkinitrd', 'openvswitch', 'pam', 'pciutils', 'ssmtp', 'supp-pack-build', 
                                'sysfsutils', 'sysklogd', 'x86_64-linux-gcc', 'x86_64-linux-binutils', 'x86_64-linux-glibc', 
                                'xcp-python-libs', 'xe-guest-utilities', 'xen', 'xsconsole', 
                                'directfb', 'glibc', 'kbd'] # missing from tampa onwards

    def run(self, arglist=None):
        # DDK VM Name = "XenServer DDK 6.1.0-58481p import" (if not altered)
        ddkVM = self.host.importDDK()
        ddkVM.createVIF(bridge=self.host.getPrimaryBridge())
        ddkVM.start()

        installedRpmList = ddkVM.execcmd("for r in `rpm -qa`; "
            "do gpl=`rpm -q --qf %{License} $r|grep -ci \"GPL\|Apache\|AFL\|Artistic\|DFSG\|MPL\"`; "
            "   if [ $gpl -ge 1 ]; then echo `rpm -q --qf %{SourceRPM} $r`; "
            "fi; done | sort | uniq")

        self.setInstalledRpmPackages(installedRpmList)

        self.ignoreRpmPackagesFromComparison()

        # Download xe-phase-3/source-ddk.iso
        self.setSourceRpmPackages()

        self.compareRpmPackages()


class TCDDKVmLifecycleOperation(TCDDKSourceCheck):
    """TC-21158 Verify DDK VM Lifecycle Operation, Storage and Network tests"""

    def run(self, arglist=None):
        # Import the DDK VM from "ddk.iso"
        cli = self.host.getCLIInstance()
        log("Import the DDK VM")
        ddkVM = self.host.importDDK()
        eth = ddkVM.createVIF(bridge=self.host.getPrimaryBridge())
        ddkVM.start()
        # Perform lifecycle operation
        log("Performing lifecycle operations on DDK VM")
        ddkVM.reboot()
        ddkVM.shutdown()
        ddkVM.start()
        ddkVM.suspend(extraTimeout=3600)
        ddkVM.resume()
        ddkVM.migrateVM(self.host, live="true")
        log("Performing network tests on DDK VM")
        # Do vif plug/unplug
        ddkVM.unplugVIF(eth)
        ddkVM.plugVIF(eth)
        ddkVM.reboot()
        log("Performing storage tests on DDK VM")
        # Do vbd plug/unplug
        userdevice = ddkVM.createDisk(sizebytes=268435456)
        ddkVM.unplugDisk(userdevice)
    

class TCDXenAPISDKSourceCheck(SourceISOCheck): # TC-18004
    """Verify Xen API SDK source iso (xe-phase-3/source-sdk.iso) content for missing RPMs."""

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Unimplemented")

class TCVerifyDom0DriverVersions(xenrt.TestCase):
    """Verify the list of Dom0 driver versions against the expected values."""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()        
        # Get the driver version file to verify against
        version = self.host.productRevision.split('-')[0]
        productName = xenrt.GEC().config.lookup(["PRODUCT_CODENAMES", version])

        driverVersionFile = "%s/data/driverversions/%s.csv" % (xenrt.TEC().lookup("XENRT_BASE"),
                                                               productName)
        xenrt.TEC().logverbose("Using Driver Version file: %s" % (driverVersionFile))
        fh = file(driverVersionFile)
        lines = fh.read().strip().split('\n')
        fh.close()

        self.expectedDrivers = {}
        for line in lines:
            driverInfo = line.strip().split(',')
            if len(driverInfo) != 4:
                raise xenrt.XRTError("Invalid Driver Info: %s" % (line))

            self.expectedDrivers[driverInfo[0]] = { 'version': driverInfo[1],
                                                    'field':   driverInfo[2],
                                                    'regex':   driverInfo[3] }

    def run(self, arglist=None):
        failed = False

        for driver in self.expectedDrivers.keys():
            try:
                actualVer = self.host.execdom0("modinfo -F %s %s" % (self.expectedDrivers[driver]['field'], driver)).strip()
                if self.expectedDrivers[driver]['regex']:
                    val = re.findall(self.expectedDrivers[driver]['regex'], actualVer)
                    if len(val) != 1:
                        xenrt.TEC().warning("Failed to get driver version for %s. Reason: Invalid regex: %s in %s" % (driver, self.expectedDrivers[driver]['regex'], actualVer))
                        failed = True
                    actualVer = val[0]
                if actualVer != self.expectedDrivers[driver]['version']:
                    xenrt.TEC().warning("Version mismatch for driver %s: Expected %s, Actual %s" % (driver, self.expectedDrivers[driver]['version'], actualVer))
                    failed = True

            except Exception, e:
                xenrt.TEC().warning("Failed to get driver info for %s. Reason: %s" % (driver, str(e)))
                failed = True

        if failed:
            raise xenrt.XRTFailure("Driver check failed")

class TCVerifyLicenseList(xenrt.TestCase):
    
    def run(self, arglist=None):
        host = self.getDefaultHost()
        
        # get script from build output for querying licenses from RPMs installed in dom0
        sh = host.sftpClient()
        try:
            sh.copyTo(xenrt.TEC().getFile("xe-phase-1/eulas/queryRpmLicenses.sh"), "/tmp/queryRpmLicenses.sh")
        except Exception, e:
            # if this file isn't present, then just exit.
            xenrt.TEC().logverbose(str(e))
            return
        finally:
            sh.close()

        # execute the script to query for licenses in RPMs installed in dom0
        host.execdom0("bash /tmp/queryRpmLicenses.sh --output=/tmp/LICENSES-LIST")
        tmp = xenrt.TEC().tempDir()
        
        # get output of script and write file on controller.
        xenrt.TEC().logverbose("Licenses from Dom 0:")
        licensesFromDom0 = host.execdom0("cat /tmp/LICENSES-LIST")
        licensesFromDom0File = "%s/licensesFromDom0" % tmp
        f = file(licensesFromDom0File, "w")
        f.write(licensesFromDom0)
        f.close()
        
        # get licenses from build output and write to file on controller
        licensesFromBuildOutputFile = xenrt.TEC().getFile("xe-phase-1/eulas/LICENSES-LIST")
        f = file(licensesFromBuildOutputFile, "r")
        licensesFromBuildOutput = f.read()
        f.close()
        xenrt.TEC().logverbose("Licenses from Build output:\n" + licensesFromBuildOutput)

        try:
            xenrt.command("diff %s %s" % (licensesFromDom0File, licensesFromBuildOutputFile))
        except:
            xenrt.TEC().warning("ERROR: New licenses found in dom0. docsource.hg/LICENSES and docsource.hg/LICENSES-LIST need to be updated using xe-phase-1/eulas/queryRpmLicenses.sh")

class TCApplyReqdPatches(xenrt.TestCase):
    
    def run(self, arglist=None):
        hosts = [ xenrt.TEC().registry.hostGet(x) for x in xenrt.TEC().registry.hostList() ]

        for host in hosts:
            host.applyRequiredPatches()
