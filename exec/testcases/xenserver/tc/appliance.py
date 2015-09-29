import xenrt, xenrt.util, xenrt.lib.xenserver
import os.path, time, re, math, string
import XenAPI
from collections import defaultdict

class _WlbApplianceVM(xenrt.TestCase):
    """Smoke test a Wlb appliance VM."""
    
    WLBSERVER_NAME = "VPXWLB"
    wlbserver = None

    def prepare(self, arglist=None):

        self.distro = "wlbapp"
        self.wlbserver_name = self.WLBSERVER_NAME
        self.vpx_os_version = xenrt.TEC().lookup("VPX_OS_VERSION", "CentOS5")
        self.host = self.getDefaultHost()
        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "distro":
                self.distro = l[1]
            elif l[0] == "name":
                self.wlbserver_name = l[1]
            elif l[0] == "host":
                self.host = self.getHost(l[1])

        g = self.host.guestFactory()(\
            self.wlbserver_name, "NO_TEMPLATE",
            password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        xenrt.TEC().registry.guestPut(self.WLBSERVER_NAME, g)
        g.host = self.host
        g.addExtraLogFile("/var/log/wlb/LogFile.log")
        if self.vpx_os_version == "CentOS7":
            self.wlbserver = xenrt.WlbApplianceServerHVM(g) # CentOS 7 VPX, HVM guest
        else:
            self.wlbserver = xenrt.WlbApplianceServer(g)
        g.importVM(self.host, xenrt.TEC().getFile("xe-phase-1/vpx-wlb.xva"))
        g.windows = False
        g.lifecycleOperation("vm-start", specifyOn=True)
        # here we should support both old (CentOS5) and new (CentOS7) WLB, disable sshcheck
        g.waitReadyAfterStart2(sshcheck=False)
        self.getLogsFrom(g)

        #self.uninstallOnCleanup(g)
        self.wlbserver.doFirstbootUnattendedSetup()
        self.wlbserver.doLogin()
        self.wlbserver.doSanityChecks()
        self.wlbserver.installSSH()
        time.sleep(30)
        self.wlbserver.doVerboseLogs()
        # restart and see if the wlb services are still up
        g.shutdown()
        g.start()
        time.sleep(60)
        self.wlbserver.doLogin()
        self.wlbserver.doSanityChecks()
        return g       

    def run(self, arglist=None):
        wlb_url="%s:%s" % (self.wlbserver.place.mainip, self.wlbserver.wlb_port)
        wlb_username=self.wlbserver.wlb_username
        wlb_password=self.wlbserver.wlb_password
        self.pool = self.getDefaultPool()
        self.pool.initialiseWLB(wlb_url, wlb_username, wlb_password)
        self.pool.deconfigureWLB()


class TC12766(_WlbApplianceVM):
    pass

class _TransferVM(xenrt.TestCase):

    SR_TYPE = "lvm"
    TR_MODE = "HTTP"
    USE_SSL = False
    SSL_VERSION = "TLSv1.2"

    def prepare(self, arglist=[]):

        self.tool_host = self.getHost("RESOURCE_HOST_0")
        self.src_host = self.getHost("RESOURCE_HOST_1")
        self.dst_host = self.getHost("RESOURCE_HOST_2")
        
        self.src_host.sr_uuid = self.src_host.getSRs(type=self.SR_TYPE)[0]
        self.dst_host.sr_uuid = self.dst_host.getSRs(type=self.SR_TYPE)[0]
        
        tool_lin = self.tool_host.getGuest("ToolLinux")
        if tool_lin.getState() <> 'DOWN': tool_lin.shutdown()
        self.tool_lin = tool_lin.cloneVM()
        self.uninstallOnCleanup(self.tool_lin)
        self.tool_lin.start()
        
#       self.tool_lin.tailor()
#       # Hack as our mirror somehow doesn't have libssh2
#       self.tool_lin.execcmd("echo 'deb http://ftp.us.debian.org/debian "
#                             "lenny main' >> /etc/apt/sources.list")
#       self.tool_lin.execcmd("apt-get update", level=xenrt.RC_OK)
#       self.tool_lin.execcmd("apt-get install curl --force-yes -y")

        tool_win = self.tool_host.getGuest("ToolWin")
        if tool_win.getState() <> 'DOWN': tool_win.shutdown()
        self.tool_win = tool_win.cloneVM()
        self.uninstallOnCleanup(self.tool_win)
        self.tool_win.start()

        g = self.src_host.getGuest("DemoLinux")
        if g.getState() <> "DOWN": g.shutdown(again=True)
        
        self.src_lin = g.copyVM(sruuid=self.src_host.sr_uuid)
#        self.src_lin = self.src_host.getGuest("DemoLinux-copy-0")
#        
        self.uninstallOnCleanup(self.src_lin)
        
        g = self.src_host.getGuest("DemoWin")
        if g.getState() <> "DOWN": g.shutdown(again=True)
        
        self.src_win = g.copyVM(sruuid=self.src_host.sr_uuid)
#        self.src_win = self.src_host.getGuest("DemoWin-copy-0")
#        
        self.uninstallOnCleanup(self.src_win)

        if self.TR_MODE.startswith("HTTP"):
            self.tool_vm = self.tool_lin
            self.get_vdi = self.httpGetVDI
            self.put_vdi = self.httpPutVDI
        elif self.TR_MODE.startswith("ISCSI"):
            self.tool_vm = self.tool_lin
        elif self.TR_MODE.startswith("BIT"):
            self.tool_vm = self.tool_win
            self.get_vdi = self.bitsGetVDI
            self.put_vdi = self.bitsPutVDI
        else:
            raise xenrt.XRTError("Unsupported transfer mode: %s" % self.TR_MODE)

    def httpGetVDI(self, tool_vm, rec):
        curl = tool_vm.execcmd('which curl').strip()
        tmp_dir = tool_vm.tempDir()
        tmp_file = os.path.join(tmp_dir, os.path.basename(rec['url_path']))
        tool_vm.execcmd("%s %s -o %s" % (curl, rec['url_full'], tmp_file))
        return tmp_file

    def httpPutVDI(self, tool_vm, filename, rec):
        curl = tool_vm.execcmd('which curl').strip()
        tool_vm.execcmd("%s -H 'Expect:' -T %s %s" % (curl, filename, rec['url_full']))

    def bitsTransVDI(self, tool_vm, rec, filename, transfer, timeout=1200):

        jobname= transfer + "-" + rec['vdi_uuid']
        
        bitsadmin = "%s\\system32\\bitsadmin.exe" % \
                    tool_vm.xmlrpcGetEnvVar("SystemRoot")

        tool_vm.xmlrpcExec("%s /create /%s %s"
                           % (bitsadmin, transfer, jobname))

        tool_vm.xmlrpcExec("%s /setsecurityflags %s 31"
                           % (bitsadmin, jobname))
        
        tool_vm.xmlrpcExec("%s /addfile %s %s %s"
                           % (bitsadmin, jobname, rec['url_full'], filename))
        
        tool_vm.xmlrpcExec("%s /resume %s" % (bitsadmin, jobname))
        
        xenrt.TEC().logverbose("Waiting for transfer to complete")

        deadline = xenrt.timenow() + timeout
        bitsnow = 0
        while True:
            info = tool_vm.xmlrpcExec("%s /info %s" % (bitsadmin, jobname),
                                      returndata=True)
            info = info.strip().splitlines()[-1].strip()
            info = re.match("{(.+)} '(.+)' (\S+) (\w+) / (\w+) (\w+) / (\w+)",
                            info).groups()
            assert info[1] == jobname
            info = { 'uuid': info[0],
                     'name': info[1],
                     'state': info[2],
                     'jobnow': int(info[3]),
                     'joball': int(info[4]),
                     'bitsnow': int(info[5]),
                     'bitsall': info[6].isdigit() and int(info[6]) or None }
            if info['state'] in ["TRANSFERRED", "ACKNOWLEDGED"]:
                assert info['bitsnow'] == info['bitsall']
                xenrt.TEC().logverbose(" ... transferred")
                tool_vm.xmlrpcExec("%s /complete %s" % (bitsadmin, jobname))
                break
            elif info['state'] in ["QUEUED", "CONNECTING", "TRANSFERRING",
                                   "TRANSIENT_ERROR"]:
                if xenrt.timenow() > deadline:
                    if info['bitsnow'] > bitsnow:
                        bitsnow = info['bitsnow']
                        # Yet another extension
                        deadline = deadline + timeout
                    else:
                        jobinfo = tool_vm.xmlrpcExec("%s /info %s /verbose"
                                                     % (bitsadmin, jobname),
                                                     returndata=True)
                        tool_vm.xmlrpcExec("%s /cancel %s"
                                           % (bitsadmin, jobname))
                        raise xenrt.XRTFailure("Bits transfer timed out",
                                               data=jobinfo)
                time.sleep(60)
            elif info['state'] in ["SUSPENDED"]:
                xenrt.TEC().warning("Somehow the job became suspended again, "
                                    "will retry to see.")
                tool_vm.xmlrpcExec("%s /resume %s" % (bitsadmin, jobname))                
            elif info['state'] in ["ERROR", "CANCELED"]:
                raise xenrt.XRTFailure("The transmition failed with status: "
                                       "%s." % info['state'])
            else:
                raise xenrt.XRTError("Unknown tranferring status: %s"
                                     % info['state'])
            
        if transfer <> "download" or tool_vm.xmlrpcFileExists(filename):
            return filename
        else:
            raise xenrt.XRTError("%s is not found in the VM" % filename)


    def bitsGetVDI(self, tool_vm, rec):
        filename = "C:\\" + os.path.basename(rec['url_path']) + ".vdi"
        return self.bitsTransVDI(tool_vm, rec, filename, "download")
    
    def bitsPutVDI(self, tool_vm, rec, file):
        self.bitsTransVDI(tool_vm, rec, file, "upload")

    def getMeta(self, vm):
        tmp_dir = xenrt.TEC().tempDir()
        metafile = os.path.join(tmp_dir, vm.getUUID() + ".meta")
        vm.exportVM(metafile, metadata=True)
        return metafile

    def restoreVM(self, host, metadata, distro):
        """ Precondition: all the VDIs are already present on the server. """
        g = host.guestFactory()(\
            "VMClone", "NO_TEMPLATE",
            password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        g.importVM(host, metadata, preserve=True,
                   sr=self.dst_host.sr_uuid, metadata=True)
        g.distro = distro
        self.getLogsFrom(g)
        self.uninstallOnCleanup(g)
        return g

    def md5sumVDI(self, host, vdi, vdi_size_unit=None, vdi_size_in_unit=None):
        script = 'if [ -z "$1" ]; then md5sum "/dev/${DEVICE}"; else dd if="/dev/${DEVICE}" bs="$1" count="$2" 2>/dev/null | md5sum; fi'
        host.execdom0("echo '%s' > /tmp/md5.sh" % script)
        host.execdom0("chmod u+x /tmp/md5.sh")
        command = "/opt/xensource/debug/with-vdi %s /tmp/md5.sh" % vdi
        if vdi_size_unit and vdi_size_in_unit:
            command += " %d %d" % (vdi_size_unit, vdi_size_in_unit)
        md5sum = host.execdom0(command, timeout=1800).splitlines()[-1].split()[0]
        if "The device is not currently attached" in md5sum:
            raise xenrt.XRTError("Device not attached when trying to md5sum")
        return md5sum
    
    def run(self, arglist=[]):

        self.dst_guests = []
        self.vdis_to_destroy = []

        for src_guest in [ self.src_lin, self.src_win ]:

##
            src_guest.tailored = True                        
            src_guest.start()
#           src_guest.checkHealth()
##
            src_vdis = src_guest.getAttachedVDIs()            
            src_guest.shutdown()

            self.meta_maps = {}

            for src_vdi in src_vdis:
                vsize = self.src_host.genParamGet("vdi",src_vdi,
                                                  "virtual-size")
                dst_vdi = self.dst_host.createVDI(vsize,
                                                  sruuid=self.dst_host.sr_uuid)
                self.vdis_to_destroy.append(dst_vdi)
                
                self.meta_maps[src_vdi] = dst_vdi

                self.src_host.transfer_vm = \
                    xenrt.lib.xenserver.host.TransferVM(self.src_host)
                self.dst_host.transfer_vm = \
                    xenrt.lib.xenserver.host.TransferVM(self.dst_host)
                
                src_ref = self.src_host.transfer_vm.expose(src_vdi,
                                                           self.TR_MODE,
                                                           read_only=False,
                                                           use_ssl=self.USE_SSL,
                                                           ssl_version=self.SSL_VERSION)
                src_rec = self.src_host.transfer_vm.get_record(src_ref)
                dst_ref = self.dst_host.transfer_vm.expose(dst_vdi,
                                                           self.TR_MODE,
                                                           read_only=False,
                                                           use_ssl=self.USE_SSL,
                                                           ssl_version=self.SSL_VERSION)
                dst_rec = self.dst_host.transfer_vm.get_record(dst_ref)
                
                vdi_file = self.get_vdi(self.tool_vm, src_rec)
                self.put_vdi(self.tool_vm, dst_rec, vdi_file)
                
                self.src_host.transfer_vm.unexpose(src_ref)
                self.dst_host.transfer_vm.unexpose(dst_ref)


# Here we need something similar to the xapi's copy plugin. However it's
# currently a bit more heavy weight for this testcase.

#             meta_file = self.getMeta(src_guest)
#             fd_in = open(meta_file, "r")
#             meta_data = fd_in.read()
#             fd_in.close()
#             for k in self.meta_maps.keys():
#                 meta_data = meta_data.replace(k, self.meta_maps[k])
#             new_meta_file = meta_file + ".new"
#             fd_out = open(new_meta_file, "w")
#             fd_out.write(meta_data)
#             fd_out.close()

#             dst_guest = self.restoreVM(self.dst_host, new_meta_file, src_guest.distro)
#             dst_guest.start()
#             dst_guest.checkHealth()

#             self.dst_guests.append(dst_guest)

#         for g in self.dst_guests:
#             g.shutdown()

            for vdi in self.meta_maps.keys():
                vdi_size_unit = None
                vdi_size_in_unit = None
                if self.SR_TYPE == "netapp":
                    src_vdi_size = int(self.src_host.genParamGet("vdi", vdi, "virtual-size"))
                    dst_vdi_size = int(self.dst_host.genParamGet("vdi", self.meta_maps[vdi], "virtual-size"))
                    if src_vdi_size != dst_vdi_size:
                        if not (0 < dst_vdi_size - src_vdi_size <= 8 * xenrt.MEGA):
                            raise xenrt.XRTFailure("Size differences between the original and the new VDI is wrong: original (%d) v.s. new (%d)" % (src_vdi_size, dst_vdi_size))
                        vdi_size_unit = \
                                  (src_vdi_size % xenrt.GIGA == 0) and xenrt.GIGA \
                                  or (src_vdi_size % xenrt.MEGA == 0) and xenrt.MEGA \
                                  or (src_vdi_size % xenrt.KILO == 0) and xenrt.KILO \
                                  or 1
                        vdi_size_in_unit = src_vdi_size / vdi_size_unit
                md5_old = self.md5sumVDI(self.src_host, vdi, vdi_size_unit, vdi_size_in_unit)
                xenrt.TEC().logverbose("VDI %s on %s has md5 checksum %s"
                                       % (vdi, self.src_host.getName(), md5_old))
                md5_new = self.md5sumVDI(self.dst_host, self.meta_maps[vdi], vdi_size_unit, vdi_size_in_unit)
                xenrt.TEC().logverbose("VDI %s on %s has md5 checksum %s"
                                       % (self.meta_maps[vdi],
                                          self.dst_host.getName(),
                                          md5_new))
                if md5_old == md5_new:
                    xenrt.TEC().logverbose("VDI is unchanged after transfer")
                else:
                    raise xenrt.XRTFailure("VDI is changed after transfer")

            xenrt.TEC().logverbose("All the VDI of %s has been transfered to "
                                 "another host without changes"
                                 % src_guest.name)
            
    def postRun(self):
        cli = self.dst_host.getCLIInstance()
        for vdi in self.vdis_to_destroy:
            try:
                cli.execute("vdi-destroy", "uuid=%s" % (vdi))
            except:
                xenrt.TEC().warning("Exception attempting to destroy VDI %s" % (vdi))

class TC11448(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = False
    SR_TYPE = "lvm"

class TC11449(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = False
    SR_TYPE = "nfs"

class TC11450(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = False
    SR_TYPE = "netapp"

class TC11451(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = False
    SR_TYPE = "lvmoiscsi"

class TC11452(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = True
    SR_TYPE = "lvm"

class TC11453(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = True
    SR_TYPE = "nfs"

class TC11454(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = True
    SR_TYPE = "netapp"

class TC11455(_TransferVM):

    TR_MODE = "HTTP"
    USE_SSL = True
    SR_TYPE = "lvmoiscsi"

# Windows BitsAdmin Tool does not support TLSv1.2,
# BitsAdmin tool (3.0 [7.0.6001]) which we use does not work well with stunnel SSLv3,
# but works well with stunnel TLSv1.

class TC11456(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = False
    SR_TYPE = "lvm"
    SSL_VERSION = "TLSv1"

class TC11457(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = False
    SR_TYPE = "nfs"
    SSL_VERSION = "TLSv1"

class TC11458(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = False
    SR_TYPE = "netapp"
    SSL_VERSION = "TLSv1"
    
class TC11459(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = False
    SR_TYPE = "lvmoiscsi"
    SSL_VERSION = "TLSv1"

class TC11460(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = True
    SR_TYPE = "lvm"
    SSL_VERSION = "TLSv1"

class TC11461(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = True
    SR_TYPE = "nfs"
    SSL_VERSION = "TLSv1"

class TC11462(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = True
    SR_TYPE = "netapp"
    SSL_VERSION = "TLSv1"

class TC11463(_TransferVM):

    TR_MODE = "BITS"
    USE_SSL = True
    SR_TYPE = "lvmoiscsi"
    SSL_VERSION = "TLSv1"

class TC11493(_TransferVM):

    TR_MODE = "ISCSI"
    USE_SSL = False
    SR_TYPE = "lvm"

class TC11494(_TransferVM):

    TR_MODE = "ISCSI"
    USE_SSL = False
    SR_TYPE = "nfs"

class TC11495(_TransferVM):

    TR_MODE = "ISCSI"
    USE_SSL = False
    SR_TYPE = "netapp"
    
class TC11496(_TransferVM):

    TR_MODE = "ISCSI"
    USE_SSL = False
    SR_TYPE = "lvmoiscsi"

class _ConversionVM(xenrt.TestCase):
    """Smoke test a Conversion appliance VM"""
    
    CONVSERVER_NAME = 'Citrix XCM Virtual Appliance'
    STOPBOOT = False
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'qa-centos-56-x86 (thick)', 'UUID': '4217d658-8479-6b1c-611f-fd502a315b79', 'WINDOWS': False, 'DISTRO': 'centos56'}]
    HOSTS = 1
    #NFSSERVER = "[NFS server]"
    #NFSSERVERPATH = "[NFS server path]"

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host0 = self.getHost("RESOURCE_HOST_0")
        
        if self.HOSTS == 2:
            self.host1 = self.getHost("RESOURCE_HOST_1")
            self.pool = xenrt.lib.xenserver.poolFactory(self.host0.productVersion)(self.host0)
            #sr = xenrt.lib.xenserver.NetAppStorageRepository(self.host0, "sr0_netapp")
            #netapp = xenrt.NetAppTarget()
            #sr.create(netapp, options=None)
            #sr.check()
            #self.host0.addSR(sr)
            #nappconf = self.host0.lookup("sr0_netapp", None)
            #self.napp = \
                #xenrt.lib.xenserver.NetAppTargetSpecified(nappconf)
        
        g = self.host0.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)
        self.vdis_to_destroy = []
        
        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host0.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code", timeout=1000, useThread=True)
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        host0_IP = self.host0.getIP()
        url = "https://%s" % host0_IP
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % host0_IP)
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host0.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() Completed")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)
        self.THIS_PIF = self.convServer.findHostMgmtPif(session)
        xenrt.TEC().logverbose("ConversionVM::self.THIS_PIF = %s" % self.THIS_PIF)
        self.NET_REF = session.xenapi.PIF.get_network(self.THIS_PIF)
        xenrt.TEC().logverbose("ConversionVM::self.NET_REF = %s" % self.NET_REF)
        self.MAN_NET_UUID = session.xenapi.network.get_uuid(self.NET_REF)
        xenrt.TEC().logverbose("ConversionVM::Management Network UUID = %s" % self.THIS_PIF)

        # Create conversion jobs for each VM in VMLIST
        for x in self.VMLIST:
            xenrt.TEC().logverbose("ConversionVM::Calling createJob(%s, %s, %s, %s, %s, %s)" %
                        (session,
                        vpx,
                        self.XEN_SERVICECRED,
                        self.VMWARE_SERVERINFO,
                        str(x['VMWAREVM']),
                        str(x['UUID']))
                        )
            JobInstance = self.convServer.createJob(session, vpx, self.XEN_SERVICECRED, self.VMWARE_SERVERINFO, str(x['VMWAREVM']), str(x['UUID']), self.MAN_NET_UUID, host0_IP)
            x['Id'] = JobInstance['Id']
            
            x['XENSERVERVM'] = self.host0.guestFactory()(str(x['VMWAREVM']),
                                 None,
                                 self.host0)
            x['XENSERVERVM'].distro = x['DISTRO']
            x['XENSERVERVM'].password = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
            x['XENSERVERVM'].enlightenedDrivers = False
            self.uninstallOnCleanup(x['XENSERVERVM'])
            if x['WINDOWS'] == True:
                x['XENSERVERVM'].windows = True
            xenrt.TEC().logverbose("ConversionVM::createJob() Completed")

        # Monitor each conversion job for completion
        for x in self.VMLIST:
            JobInstance = vpx.job.get(self.XEN_SERVICECRED, x['Id'])
            while JobInstance['State'] != 3 or JobInstance['State'] != 4 or JobInstance['State'] != 5:
                JobInstance = vpx.job.get(self.XEN_SERVICECRED, x['Id'])
                xenrt.TEC().logverbose("VM = %s, Id = %s, State = %s, PercentComplete = %s" %
                                        (x['XENSERVERVM'].getName(),
                                        x['Id'],
                                        JobInstance['State'],
                                        JobInstance['PercentComplete'])
                                        )
                if JobInstance['State'] == 3:
                    xenrt.TEC().logverbose("ConversionVM::Job completed, State = %s" % JobInstance['State'])
                    
                    # Set imported VM's UUID
                    x['XenServerVMUuid'] = JobInstance['XenServerVMUuid']
                    xenrt.TEC().logverbose("ConversionVM::XenServerVMUuid = %s" % str(x['XenServerVMUuid']))
                    
                    # Set imported VM's MAC address
                    x['MAC'] = self.host0.execdom0("xe vif-list vm-uuid=%s params=MAC device=0 | awk -F': ' '{print $2}'" % str(x['XenServerVMUuid']))
                    xenrt.TEC().logverbose("ConversionVM::MAC = %s" % str(x['MAC']))
                    
                    # Get VPX log files
                    vpxlog = open('/tmp/con-vpx-job.log', 'w')
                    xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                    vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                    xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                    vpxlog.write(vpxlogcontents)
                    vpxlog.close()
                    xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                    xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                    xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                    break
                if JobInstance['State'] == 4:
                    xenrt.TEC().logverbose("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                    
                    # Get VPX log files
                    vpxlog = open('/tmp/con-vpx-job.log', 'w')
                    xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                    vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                    xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                    vpxlog.write(vpxlogcontents)
                    vpxlog.close()
                    xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                    xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                    xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                    raise xenrt.XRTFailure("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                if JobInstance['State'] == 5:
                    xenrt.TEC().logverbose("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
                    
                    # Get VPX log files
                    vpxlog = open('/tmp/con-vpx-job.log', 'w')
                    xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                    vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                    xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                    vpxlog.write(vpxlogcontents)
                    vpxlog.close()
                    xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                    xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                    xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                    raise xenrt.XRTFailure("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
                
                # Sleep for 20 seconds before calling vpx.job.get() again
                time.sleep(20)

        # Don't boot imported VMs for stress test
        if self.STOPBOOT == True:
            return

        # Boot and validate VMs
        for x in self.VMLIST:
            bridge = self.host0.getPrimaryBridge()
            vifname = "eth0"
            mac = x['MAC'].rstrip()
            
            # Set VM's VIF w/o IP address
            xenrt.TEC().logverbose("ConversionVM::Setting x['XENSERVERVM'].vifs = [vifname, bridge, mac]")
            x['XENSERVERVM'].vifs = [(vifname, bridge, mac, None)]
            xenrt.TEC().logverbose("ConversionVM::Setting x['XENSERVERVM'].vifs = [vifname, bridge, mac] completed")
            xenrt.TEC().logverbose("ConversionVM::x['XENSERVERVM'].vifs[0] = %s" % str(x['XENSERVERVM'].vifs[0]))
            xenrt.TEC().logverbose("ConversionVM::getVIF(%s) = %s" % (vifname, str(x['XENSERVERVM'].getVIF(vifname))))

            # Start VM
            xenrt.TEC().logverbose("ConversionVM::Starting %s" % str(x['VMWAREVM']))
            #x['XENSERVERVM'].lifecycleOperation("vm-start",specifyOn=True)
            #x['XENSERVERVM'].start(specifyOn=True, managenetwork=self.NET_REF[0], managebridge=bridge)
            x['XENSERVERVM'].start(specifyOn=True, managebridge=bridge)
            xenrt.TEC().logverbose("Waiting for the VM to enter the UP state")
            x['XENSERVERVM'].poll("UP", pollperiod=5)
            xenrt.TEC().logverbose("ConversionVM::%s started" % str(x['VMWAREVM']))
            
            # Find and set VM's IP address
            xenrt.TEC().logverbose("ConversionVM::calling arpwatch()")
            x['XENSERVERVM'].mainip = self.host0.arpwatch(bridge, mac, timeout=1800)
            xenrt.TEC().logverbose("ConversionVM::calling arpwatch() completed")
            if not x['XENSERVERVM'].mainip:
                raise xenrt.XRTFailure("Did not find an IP address")
            xenrt.TEC().logverbose("ConversionVM::x['XENSERVERVM'].mainip = %s" % str(x['XENSERVERVM'].mainip))
            
            # Set VM's VIF w/ IP address
            x['XENSERVERVM'].vifs = [(vifname, bridge, mac, str(x['XENSERVERVM'].mainip))]
            xenrt.TEC().logverbose("ConversionVM::x['XENSERVERVM'].vifs[0] = %s" % str(x['XENSERVERVM'].vifs[0]))
            xenrt.TEC().logverbose("ConversionVM::getVIF(%s) = %s" % (vifname, str(x['XENSERVERVM'].getVIF(vifname))))
            
            # Get VM's VDI and append to vdis_to_destroy
            x['VDI'] = self.host0.execdom0("xe vbd-list vm-uuid=%s device=hda params=vdi-uuid| awk -F': ' '{print $2}'" % str(x['XenServerVMUuid']))
            xenrt.TEC().logverbose("ConversionVM::VDI = %s" % str(x['VDI']))
            self.vdis_to_destroy.append(x['VDI'].rstrip())
            xenrt.TEC().logverbose("ConversionVM::self.vdis_to_destroy = %s" % str(self.vdis_to_destroy))

            # Windows VM
            if x['WINDOWS'] == True:
                xenrt.TEC().logverbose("ConversionVM::Windows guest OS detected")
                x['XENSERVERVM'].windows = True
                
                # Install PV Drivers
                xenrt.TEC().logverbose("ConversionVM::Installing PV drivers")
                x['XENSERVERVM'].installDrivers()
                xenrt.TEC().logverbose("ConversionVM::PV drivers installed")
                
                # Introduce VM to existing host
                x['XENSERVERVM'].existing(self.host0)
                
                # Check VM
                xenrt.TEC().logverbose("ConversionVM::Checking VM")
                x['XENSERVERVM'].check()
                xenrt.TEC().logverbose("ConversionVM::VM checked")
                
                # Eject XenTools ISO
                xenrt.TEC().logverbose("ConversionVM::Ejecting XenTools ISO")
                x['XENSERVERVM'].changeCD(None)
                xenrt.TEC().logverbose("ConversionVM::XenTools ISO ejected")
                
                # Shutdown VM
                xenrt.TEC().logverbose("ConversionVM::Shutting down %s" % str(x['VMWAREVM']))
                x['XENSERVERVM'].shutdown()
                xenrt.TEC().logverbose("ConversionVM::%s shutdown" % str(x['VMWAREVM']))

            # Linux VM
            elif x['WINDOWS'] == False:
                xenrt.TEC().logverbose("ConversionVM::Linux guest OS detected")
                x['XENSERVERVM'].windows = False
                
                # Install Linux Tools
                #xenrt.TEC().logverbose("ConversionVM::Installing Tools")
                #try:
                    #x['XENSERVERVM'].installTools()
                #except:
                    # Commenting out because vbd-destroy is failing
                    #raise xenrt.XRTError("installTools() failed")
                    #xenrt.TEC().logverbose("installTools() failed")
                #xenrt.TEC().logverbose("ConversionVM::Tools Installed")
                
                # Check VM
                xenrt.TEC().logverbose("ConversionVM::Checking VM")
                x['XENSERVERVM'].check()
                xenrt.TEC().logverbose("ConversionVM::VM checked")
                
                # Eject XenTools ISO
                xenrt.TEC().logverbose("ConversionVM::Ejecting XenTools ISO")
                x['XENSERVERVM'].changeCD(None)
                xenrt.TEC().logverbose("ConversionVM::XenTools ISO ejected")
                
                # Shutdown VM
                xenrt.TEC().logverbose("ConversionVM::Shutting down %s" % str(x['VMWAREVM']))
                x['XENSERVERVM'].shutdown()
                xenrt.TEC().logverbose("ConversionVM::%s shutdown" % str(x['VMWAREVM']))
        #self.pause("test paused")
        return

    #def postRun(self):
        #self.host = self.getDefaultHost()
        #cli = self.host.getCLIInstance()
        #for vdi in self.vdis_to_destroy:
            #try:
                #cli.execute("vdi-destroy", "uuid=%s" % (vdi))
            #except:
                #xenrt.TEC().warning("Exception attempting to destroy VDI %s" % (vdi))

class TC15638(_ConversionVM):
    """Import and install a Conversion appliance VM."""
    
    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getHost("RESOURCE_HOST_0")

        for arg in arglist:
            l = string.split(arg, "=", 1)
            if l[0] == "name":
                self.convServerName = l[1]
            elif l[0] == "host":
                self.host = self.getHost(l[1])
                
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        
        xenrt.TEC().registry.guestPut(self.convServerName, g)
        g.host = self.host

        # Set Session
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)

        # Import VPX
        self.convServer = xenrt.ConversionApplianceServer(g)
        xenrt.TEC().logverbose("Importing Conversion VPX")
        g.importVM(self.host, xenrt.TEC().getFile("xe-phase-1/vpx-conversion.xva"))
        xenrt.TEC().logverbose("Conversion VPX Imported")
        g.windows = False
        vm_uuid = g.getUUID()
        # First get the management network's UUID
        this_pif = self.convServer.findHostMgmtPif(session)
        this_network = session.xenapi.PIF.get_network(this_pif)
        # Now update the XCM VPX to use this new network
        self.convServer.updateXcmNetwork(session, vm_uuid, this_network)
        g.lifecycleOperation("vm-start",specifyOn=True)
        
        # Wait for the VM to come up.
        xenrt.TEC().logverbose("Waiting for the VM to enter the UP state")
        g.poll("UP", pollperiod=5)
        # Wait VM to boot up
        time.sleep(300)
        self.getLogsFrom(g)
        #self.uninstallOnCleanup(g)
        self.convServer.doFirstbootUnattendedSetup()
        
        # Check VPX

        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() Completed")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)
        
        # Get VPX log file
        vpxlog = open('/tmp/con-vpx-install.log', 'w')
        xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
        vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
        xenrt.TEC().logverbose("ConversionVM::getlog() completed")
        vpxlog.write(vpxlogcontents)
        vpxlog.close()
        xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
        xenrt.TEC().copyToLogDir('/tmp/con-vpx-install.log')
        xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
        return
    
class TC16129(_ConversionVM):
    VMLIST = [ {'VMWAREVM': 'qa-centos-56-x86 (thick)', 'UUID': '4217d658-8479-6b1c-611f-fd502a315b79', 'WINDOWS': False, 'DISTRO': 'centos56'}]

class TC16140(_ConversionVM):
    #Windows VMs
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-win2k3-x86 (thick)', 'UUID': '423ac32d-0872-5094-cd60-f603f3864e72', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"},
            {'VMWAREVM': 'xenrt-win2k3-x64 (thin)', 'UUID': '423a2a7c-9941-8f1c-db3a-4b1a557c8c76', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"},
            {'VMWAREVM': 'xenrt-win2k8-sp2-x86 (thick)', 'UUID': '423a64b1-05fb-ea5b-846b-f1a938dc3448', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"},
            {'VMWAREVM': 'xenrt-win2k8-x64 (thin)', 'UUID': '423ac769-0f83-d709-23cd-a0adc2730841', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"},
            {'VMWAREVM': 'xenrt-win2k8r2-x64 (thin)', 'UUID': '423a782f-578e-95c5-b48c-08153a04fea8', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"},
            {'VMWAREVM': 'xenrt-winxp-sp3-x86 (thick)', 'UUID': '423ac449-b7ef-5ec9-92be-35ae4fc81429', 'WINDOWS': True, 'DISTRO': "winxpsp3"},
            {'VMWAREVM': 'xenrt-vista-sp2-x86 (thick)', 'UUID': '423a8bb2-abc2-ade7-c070-41b532b92ecb', 'WINDOWS': True, 'DISTRO': "vistaeesp2"},
            {'VMWAREVM': 'xenrt-win7-x64 (thick)', 'UUID': '423ab0d1-9967-3ac0-5bf6-91347c7626a1', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"},
            {'VMWAREVM': 'xenrt-win7-x86 (thick)', 'UUID': '423a2585-072a-07a7-ef7f-fdebe740886a', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC15570(_ConversionVM):
    #vCenter 4.1
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x64 (tools)', 'UUID': '423edfb4-2ea5-9493-1afe-588b7f235e44', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC15572(_ConversionVM):
    #vCenter 4.0
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x64 (tools)', 'UUID': '423e96d1-a571-3ef2-4a42-76dd70fb0099', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC15580(_ConversionVM):
    #ESXi 4.1
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-41-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x64 (tools)', 'UUID': '423edfb4-2ea5-9493-1afe-588b7f235e44', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC15584(_ConversionVM):
    #ESXi 4.0
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-05.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x64 (tools)', 'UUID': '423e96d1-a571-3ef2-4a42-76dd70fb0099', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC15578(_ConversionVM):
    #ESX 4.1
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-41-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k3-x64 (tools)', 'UUID': '423e5d52-3945-d370-cdb3-f6dccaa145dc', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC15582(_ConversionVM):
    #ESX 4.0
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k3-x64 (tools)', 'UUID': '423e5601-abb0-6d97-c2e1-7ae6df08094c', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17067(_ConversionVM):
    #Linux VMs
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-centos-55-x64 (thin)', 'UUID': '423ae8cb-8b5b-614d-36a4-754d5011b19a', 'WINDOWS': False, 'DISTRO': "centos55"},
            {'VMWAREVM': 'xenrt-centos-55-x86 (thin)', 'UUID': '423ade2e-74f2-18e1-2b68-b8e67f479067', 'WINDOWS': False, 'DISTRO': "centos55"},
            {'VMWAREVM': 'xenrt-redhat-54-x64 (thin)', 'UUID': '423ed201-9c9f-b0ab-979d-7db9af6cb292', 'WINDOWS': False, 'DISTRO': "rhel54"},
            {'VMWAREVM': 'xenrt-redhat-54-x86 (thin)', 'UUID': '423edf6c-59c2-2117-1b81-d19df361b498', 'WINDOWS': False, 'DISTRO': "rhel54"},
            {'VMWAREVM': 'xenrt-sles-9-x64 (thin)', 'UUID': '423e51b4-cfc3-e750-773d-b65eed56d054', 'WINDOWS': False, 'DISTRO': "sles94"},
            {'VMWAREVM': 'xenrt-sles-9-x86 (thin)', 'UUID': '423ed8de-ab0f-87cb-c6f8-8807e67707da', 'WINDOWS': False, 'DISTRO': "sles94"},
            {'VMWAREVM': 'xenrt-oracle-55-x64 (thin)', 'UUID': '423e96be-2918-61f2-3bab-128773f93062', 'WINDOWS': False, 'DISTRO': "oel55"},
            {'VMWAREVM': 'xenrt-oracle-55-x86 (thin)', 'UUID': '423e2465-0be0-683d-8977-2baf93a13172', 'WINDOWS': False, 'DISTRO': "oel55"},
            {'VMWAREVM': 'xenrt-debian-5010-x64 (thin)', 'UUID': '423effad-5e17-3d02-5710-258c0daefb67', 'WINDOWS': False, 'DISTRO': "debian50"},
            {'VMWAREVM': 'xenrt-debian-504-x86 (thin)', 'UUID': '423e8b1f-8eb9-83bc-4e8c-e794c009edc3', 'WINDOWS': False, 'DISTRO': "debian50"},
            {'VMWAREVM': 'xenrt-ubuntu-904-x64 (thin)', 'UUID': '423ef560-6b69-aa39-fa99-962621037c9b', 'WINDOWS': False, 'DISTRO': "ubuntu1004"},
            {'VMWAREVM': 'xenrt-ubuntu-904-x86 (thin)', 'UUID': '423e352a-56bf-774c-6732-6931fa53a49d', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC17136(_ConversionVM):
    STOPBOOT = True
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = []
    VM1 = {'VMWAREVM': 'vm-500', 'UUID': '423aca02-c941-88ae-6348-5ce07bbe6b0d', 'WINDOWS': False, 'DISTRO': 'centos56'}
    TOTALJOBS = 505
    while len(VMLIST) < TOTALJOBS:
        VMLIST.append(VM1)

class TC17632(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x64 (thin)', 'UUID': '423eaad4-76cf-7e22-d2dd-0c2369d6c45d', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17631(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x86 (thin)', 'UUID': '423ebd97-1747-19f1-4a6c-fa2d11020065', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17630(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win7-x86 (thin)', 'UUID': '423eefef-d015-6ca1-8109-9e0b5d1af69d', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17629(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win7-x64 (thin)', 'UUID': '423f8132-ef11-333b-9eb4-ffdafadb2fe2', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17628(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-vista-sp2-x86 (thin)', 'UUID': '423e1bcd-d163-40c6-5db3-74230b1bb345', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17627(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-winxp-sp3-x86 (thin)', 'UUID': '423eae13-1a86-d378-dc06-cd819ff79638', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

class TC17626(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-win2k8r2-x64 (thin)', 'UUID': '423a782f-578e-95c5-b48c-08153a04fea8', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17625(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-win2k8-x64 (thin)', 'UUID': '423ac769-0f83-d709-23cd-a0adc2730841', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17613(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-win2k8-sp2-x86 (thin)', 'UUID': '423a64b1-05fb-ea5b-846b-f1a938dc3448', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17644 (_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-ubuntu-904-x86 (thin)', 'UUID': '423e352a-56bf-774c-6732-6931fa53a49d', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC17643(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-ubuntu-904-x64 (thin)', 'UUID': '423ef560-6b69-aa39-fa99-962621037c9b', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC17642 (_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-debian-504-x86 (thin)', 'UUID': '423e8b1f-8eb9-83bc-4e8c-e794c009edc3', 'WINDOWS': False, 'DISTRO': "debian50"}]

class TC17641(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-debian-5010-x64 (thin)', 'UUID': '423effad-5e17-3d02-5710-258c0daefb67', 'WINDOWS': False, 'DISTRO': "debian50"}]

class TC17640(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-oracle-55-x86 (thin)', 'UUID': '423e2465-0be0-683d-8977-2baf93a13172', 'WINDOWS': False, 'DISTRO': "oel55"}]

class TC17639(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-oracle-55-x64 (thin)', 'UUID': '423e96be-2918-61f2-3bab-128773f93062', 'WINDOWS': False, 'DISTRO': "oel55"}]

class TC17638(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-sles-9-x86 (thin)', 'UUID': '423ed8de-ab0f-87cb-c6f8-8807e67707da', 'WINDOWS': False, 'DISTRO': "sles94"}]

class TC17637(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-sles-9-x64 (thin)', 'UUID': '423e51b4-cfc3-e750-773d-b65eed56d054', 'WINDOWS': False, 'DISTRO': "sles94"}]

class TC17636(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-redhat-54-x86 (thin)', 'UUID': '423edf6c-59c2-2117-1b81-d19df361b498', 'WINDOWS': False, 'DISTRO': "rhel54"}]

class TC17635(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-redhat-54-x64 (thin)', 'UUID': '423ed201-9c9f-b0ab-979d-7db9af6cb292', 'WINDOWS': False, 'DISTRO': "rhel54"}]

class TC17634(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-centos-55-x86 (thin)', 'UUID': '423ade2e-74f2-18e1-2b68-b8e67f479067', 'WINDOWS': False, 'DISTRO': "centos55"}]

class TC17633(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'xenrt-centos-55-x64 (thin)', 'UUID': '423ae8cb-8b5b-614d-36a4-754d5011b19a', 'WINDOWS': False, 'DISTRO': "centos55"}]

class TC17688(_ConversionVM):
    STOPBOOT = True
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': '4 NICs', 'UUID': '423a3bca-dbbf-e031-49b8-8bffc3163592', 'WINDOWS': False, 'DISTRO': 'centos56'}]

class TC17687(_ConversionVM):
    STOPBOOT = True
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': '16 Disks', 'UUID': '423ad808-08fa-c84b-17da-8e575c91ced9', 'WINDOWS': False, 'DISTRO': 'centos56'}]

class TC17686(_ConversionVM):
    STOPBOOT = True
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': '2 NICs', 'UUID': '423a9f84-6900-2eb0-8648-9bd611d6a405', 'WINDOWS': False, 'DISTRO': 'centos56'}]

class TC17685(_ConversionVM):
    STOPBOOT = True
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': '0 NICs', 'UUID': '423aa608-7e2e-b969-fe49-a7dfc44fd9bf', 'WINDOWS': False, 'DISTRO': 'centos56'}]

# ESXi 4.1 Tools
class TC17784(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-vista-sp2-x86 (tools)', 'UUID': '423e6f15-555c-3fe0-0a24-cfe32a1229b8', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17785(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x64 (tools)', 'UUID': '423edfb4-2ea5-9493-1afe-588b7f235e44', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17786(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x86 (tools)', 'UUID': '423ea8f1-77a9-eeb6-ebea-52fdd19af5b5', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17787(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k8r2-x64 (tools)', 'UUID': '423e782b-6d7a-7d49-237c-3a0d1f1c7f6e', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17788(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k8-sp2-x86 (tools)', 'UUID': '423e923a-3aa4-ead0-8d47-c413a1ae42ee', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17789(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k8-x64 (tools)', 'UUID': '423e01f7-4551-fb9e-16ee-a663bfaa8148', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17790(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win7-x64 (tools)', 'UUID': '423e1254-a2d2-db2a-fdbb-9f96be0a6271', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17791(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win7-x86 (tools)', 'UUID': '423eedbe-d342-122f-2820-9d73906d95af', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17792(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-winxp-sp3-x86 (tools)', 'UUID': '423e5d0e-f9b3-670b-28d3-94d8469153a8', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESXi 4.1 No Tools
class TC17793(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-vista-sp2-x86 (thin)', 'UUID': '423e4298-138f-9ffd-feac-1dfb3faa2bc6', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17794(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x64 (thin)', 'UUID': '423e213a-a58c-1bb8-94d1-cfd3dd20675c', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17795(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x86 (thin)', 'UUID': '423e073d-fea9-3628-2ddd-fcb05871420d', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17796(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k8r2-x64 (thin)', 'UUID': '423e020d-662f-fe51-2322-f74cf47dd495', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17797(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k8-sp2-x86 (thin)', 'UUID': '423e0409-5ca7-4c65-3acf-459f12a90ecd', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17798(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k8-x64 (thin)', 'UUID': '423e9d45-d040-f047-e729-3621d69c933a', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17799(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win7-x64 (thin)', 'UUID': '423e6fe7-ba9d-8a2c-79e0-fcc36fefff62', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17800(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win7-x86 (thin)', 'UUID': '4217e020-14da-84c7-d6a8-fa9e96cfeb40', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17801(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-winxp-sp3-x86 (thin)', 'UUID': '423e9942-b0dd-ccfc-868c-69b07e1f7634', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESXi 4.0 Tools
class TC17813(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-vista-sp2-x86 (tools)', 'UUID': '423ef455-7c84-a053-4f00-6d46ece2008d', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17814(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x64 (tools)', 'UUID': '423e96d1-a571-3ef2-4a42-76dd70fb0099', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17815(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x86 (tools)', 'UUID': '423e94bf-cbd5-c01f-61b4-74fc2972776c', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17816(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k8r2-x64 (tools)', 'UUID': '423ebd24-f21a-3ae2-4d94-be3e3aebb322', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17817(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k8-sp2-x86 (tools)', 'UUID': '423e8af1-d03c-e0e9-0ec1-25f3a8d3dcb5', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17818(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k8-x64 (tools)', 'UUID': '423e6e5f-aa8a-3316-efc3-027a73d5488c', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17819(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win7-x64 (tools)', 'UUID': '423ec213-2927-4891-460d-6ffd1ec9db99', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17820(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win7-x86 (tools)', 'UUID': '423e1bcf-aaac-7c90-049e-d4da07852e31', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17821(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-winxp-sp3-x86 (tools)', 'UUID': '423e503d-4f28-999d-8abb-b7b36394c1f9', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESXi 4.0 No Tools
class TC17804(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-vista-sp2-x86 (thin)', 'UUID': '423e1bcd-d163-40c6-5db3-74230b1bb345', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17805(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x64 (thin)', 'UUID': '423eaad4-76cf-7e22-d2dd-0c2369d6c45d', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17806(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k3-x86 (thin)', 'UUID': '423ebd97-1747-19f1-4a6c-fa2d11020065', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17807(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k8r2-x64 (thin)', 'UUID': '423edc09-535d-21b1-e4f2-6e90d2c9c02c', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17808(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k8-sp2-x86 (thin)', 'UUID': '423e5273-332a-7680-5dba-82533cd8ba58', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17809(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win2k8-x64 (thin)', 'UUID': '423ebb00-b321-da16-010a-d6d977cc2748', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17810(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win7-x64 (thin)', 'UUID': '423f8132-ef11-333b-9eb4-ffdafadb2fe2', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17811(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi40-win7-x86 (thin)', 'UUID': '423eefef-d015-6ca1-8109-9e0b5d1af69d', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17812(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': 'esxi40-winxp-sp3-x86 (thin)', 'UUID': '423eae13-1a86-d378-dc06-cd819ff79638', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESX 4.1 No Tools
class TC17823(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-vista-sp2-x86 (thin)', 'UUID': '423ea40b-c748-097f-2a12-ed71d75a43c0', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17824(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k3-x64 (thin)', 'UUID': '423e4ff9-85c2-4d5a-4c62-17c2062ff757', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17825(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k3-x86 (thin)', 'UUID': '423e6957-053a-1a71-d436-cc1c11feeef0', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17826(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k8r2-x64 (thin)', 'UUID': '423e95fe-608d-ce0a-6ecf-823f45c228a4', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17827(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k8-sp2-x86 (thin)', 'UUID': '423eb9cb-72c3-29de-c726-e0128d41d370', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17828(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k8-x64 (thin)', 'UUID': '423ea87c-165b-e0ec-1556-dd328c1ec06f', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17829(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win7-x64 (thin)', 'UUID': '423e35e8-6b1a-8361-bc6e-724caf435261', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17830(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win7-x86 (thin)', 'UUID': '423e7002-1dbb-1bdf-c3a4-5eff4f114d4f', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17831(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-winxp-sp3-x86 (thin)', 'UUID': '42177e74-a87c-3f0e-d1c4-c1c615658561', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESX 4.1 Tools
class TC17832(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-vista-sp2-x86 (tools)', 'UUID': '423e950e-a45b-9b7c-45dc-2456e8fee89e', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17833(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k3-x64 (tools)', 'UUID': '423e5d52-3945-d370-cdb3-f6dccaa145dc', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17834(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k3-x86 (tools)', 'UUID': '423e1685-96c2-9562-6ae0-82e9be1d4329', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17835(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k8r2-x64 (tools)', 'UUID': '423e89b7-6f58-dba7-ec05-a2d715da6899', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17836(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k8-sp2-x86 (tools)', 'UUID': '423e9acc-f45f-89e7-6e42-2ce5d3b9d184', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17837(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-win2k8-x64 (tools)', 'UUID': '423e2756-87a3-2f40-ffba-db53a3e6342a', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17838(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win7-x64 (tools)', 'UUID': '423e8529-2322-ce96-2846-ae1943beb75f', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17839(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win7-x86 (tools)', 'UUID': '423e6137-3324-2a45-d668-4e4df7340c51', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17840(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-winxp-sp3-x86 (tools)', 'UUID': '42179222-bd78-7666-1982-2487807ef9df', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESX 4.0 Tools
class TC17850(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-40-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': 'esxi40-vista-sp2-x86 (tools)', 'UUID': '423e4bdd-db60-2176-3148-cf94e09dd755', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17851(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k3-x64 (tools)', 'UUID': '423e5601-abb0-6d97-c2e1-7ae6df08094c', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17852(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k3-x86 (tools)', 'UUID': '423e1486-6a98-ac58-58a1-1ae6a8f88080', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17853(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k8r2-x64 (tools)', 'UUID': '423e08d8-78f3-1d35-e2dc-4ae991d8e858', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17854(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k8-sp2-x86 (tools)', 'UUID': '423e1289-1a18-ed30-7cff-b200fcfa2b08', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17855(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k8-x64 (tools)', 'UUID': '423eb439-4ead-20d0-c405-20a27be13a74', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17856(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win7-x64 (tools)', 'UUID': '423e160c-4fd1-c0d6-e70d-d131a64cf7a6', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17857(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win7-x86 (tools)', 'UUID': '423e1b80-e820-5803-8ef7-b692c939c72b', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17858(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-winxp-sp3-x86 (tools)', 'UUID': '423fa045-8097-1cbc-9a8c-cd0aa6cb6fd6', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESX 4.0 No Tools
class TC17841(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-vista-sp2-x86 (thin)', 'UUID': '423e4b6b-5f9d-1a60-ac91-16e6bfba2de3', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17842(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k3-x64 (thin)', 'UUID': '423e938a-19b5-20ba-c7bb-f9392373230f', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17843(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k3-x86 (thin)', 'UUID': '423e1f90-9be9-8f5e-4db6-6e925c9c9f66', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17844(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k8r2-x64 (thin)', 'UUID': '423e179e-0b3b-26c8-416b-4fa5ead15bd4', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17845(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k8-sp2-x86 (thin)', 'UUID': '423eae40-15a9-6d2b-4f51-4db822bbde7d', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17846(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win2k8-x64 (thin)', 'UUID': '423e3607-87f4-d931-5aa2-71a8981955f6', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17847(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win7-x64 (thin)', 'UUID': '423ea18b-d6dc-7e99-2f57-08f49894b542', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17848(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-win7-x86 (thin)', 'UUID': '423e6fc6-4b8b-de08-e03e-5945114a9bb1', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17849(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-02.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx40-winxp-sp3-x86 (thin)', 'UUID': '423f99e7-f13a-2a92-fc39-0c736fbc479d', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESXi 5.0 Tools
class TC17868(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-vista-sp2-x86 (tools)', 'UUID': '423faf46-60e9-4de3-42e4-3d5cc83a7175', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17869(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k3-x64 (tools)', 'UUID': '423fd63a-9c6f-dbe1-c95c-6425000ad287', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17870(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k3-x86 (tools)', 'UUID': '423ff93b-ff18-529d-abf8-ba765db308f0', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17871(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k8r2-x64 (tools)', 'UUID': '423fe68f-ef5f-c085-6b72-7fdeb9ee11c9', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17872(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k8-sp2-x86 (tools)', 'UUID': '42029797-e0c2-9cfa-ac3ea2-effe5fe2e1', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17873(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k8-sp2-x64 (tools)', 'UUID': '4202f4fb-c427-7d3a-56e30b-eaa183d760', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17874(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win7-x64 (tools)', 'UUID': '423fe702-d3b3-c657-9321-63744fe4a31c', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17875(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win7-x86 (tools)', 'UUID': '423fe96f-a281-c115-ffd8-d1d3104fc53e', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17876(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-winxp-sp3-x86 (tools)', 'UUID': '423f04d7-27aa-7f46-6e1f-10305881f742', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

# ESXi 5.0 No Tools
class TC17859(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-vista-sp2-x86 (thin)', 'UUID': '423f0c41-f9e1-52a0-3565-adbc6517b81f', 'WINDOWS': True, 'DISTRO': "vistaeesp2"}]

class TC17860(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k3-x64 (thin)', 'UUID': '423f3eb8-72ce-5818-c77f-9482ae440f22', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17861(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k3-x86 (thin)', 'UUID': '423f025a-ecaf-d36b-eaa9-5a6571e55143', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]

class TC17862(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k8r2-x64 (thin)', 'UUID': '423f533c-6e1e-94e8-df84-98fe9e17d697', 'WINDOWS': True, 'DISTRO': "ws08r2-x64"}]

class TC17863(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k8-sp2-x86 (thin)', 'UUID': '423f0d1e-211c-b487-4fe4-d280f5742a10', 'WINDOWS': True, 'DISTRO': "ws08sp2-x86"}]

class TC17864(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k8-x64 (thin)', 'UUID': '423f0f1d-4083-4c50-f326-dbad7fd0f2a1', 'WINDOWS': True, 'DISTRO': "ws08sp2-x64"}]

class TC17865(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win7-x64 (thin)', 'UUID': '42330433-7e5b-be16-66e2-a6166a050a21', 'WINDOWS': True, 'DISTRO': "win7sp1-x64"}]

class TC17866(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win7-x86 (thin)', 'UUID': '423f2777-9de8-84b9-0f14-89e059694447', 'WINDOWS': True, 'DISTRO': "win7sp1-x86"}]

class TC17867(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-winxp-sp3-x86 (thin)', 'UUID': '423ff85b-cde7-4e9a-593a-ca99fd389548', 'WINDOWS': True, 'DISTRO': "winxpsp3"}]

class TC17883(_ConversionVM):
    """Connect using invalid XenServer credentials"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)
        
        # Test invalid XenServer password
        self.XEN_SERVICECRED = {'Username': 'root', 'Password': 'foo'}
        xenrt.TEC().logverbose("ConversionVM::self.XEN_SERVICECRED = %s" % self.XEN_SERVICECRED)
        xenrt.TEC().logverbose("ConversionVM::Calling getVMList() w/ invalid XenServer password")
        try:
            self.convServer.getVMList(session, vpx, self.XEN_SERVICECRED, self.VMWARE_SERVERINFO)
        except Exception, e:
            xenrt.TEC().logverbose("ConversionVM::Exception = %s" % e)
            xenrt.TEC().logverbose("ConversionVM::Test passed, getVMList() failed w/ invalid XenServer password")
            # Test invalid XenServer username
            self.XEN_SERVICECRED = {'Username': 'foo', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
            xenrt.TEC().logverbose("ConversionVM::self.XEN_SERVICECRED = %s" % self.XEN_SERVICECRED)
            xenrt.TEC().logverbose("ConversionVM::Calling getVMList() w/ invalid XenServer username")
            try:
                self.convServer.getVMList(session, vpx, self.XEN_SERVICECRED, self.VMWARE_SERVERINFO)
            except Exception, e:
                xenrt.TEC().logverbose("ConversionVM::Exception = %s" % e)
                xenrt.TEC().logverbose("ConversionVM::Test passed, getVMList() failed w/ invalid XenServer username")
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                self.XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                return
            
            # Get VPX log files
            vpxlog = open('/tmp/con-vpx-job.log', 'w')
            xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
            self.XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
            vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
            xenrt.TEC().logverbose("ConversionVM::getlog() completed")
            vpxlog.write(vpxlogcontents)
            vpxlog.close()
            xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
            xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
            xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
            
            raise xenrt.XRTFailure("ConversionVM::Test failed, getVMList() completed successfully w/ invalid XenServer username")
        
        # Get VPX log files
        vpxlog = open('/tmp/con-vpx-job.log', 'w')
        xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
        self.XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
        vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
        xenrt.TEC().logverbose("ConversionVM::getlog() completed")
        vpxlog.write(vpxlogcontents)
        vpxlog.close()
        xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
        xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
        xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
        
        raise xenrt.XRTFailure("ConversionVM::Test failed, getVMList() completed successfully w/ invalid XenServer password")

class TC17882(_ConversionVM):
    """Connect to an invalid VMware host"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'foo.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)
        
        # Test invalid VMware hostname
        xenrt.TEC().logverbose("ConversionVM::self.VMWARE_SERVERINFO['Hostname'] = %s" % self.VMWARE_SERVERINFO['Hostname'])
        xenrt.TEC().logverbose("ConversionVM::Calling getVMList() w/ invalid VMware hostname")
        try:
            self.convServer.getVMList(session, vpx, self.XEN_SERVICECRED, self.VMWARE_SERVERINFO)
        except Exception, e:
            xenrt.TEC().logverbose("ConversionVM::Exception = %s" % e)
            xenrt.TEC().logverbose("ConversionVM::Test passed, getVMList() failed w/ invalid VMware hostname")
            
            # Get VPX log files
            vpxlog = open('/tmp/con-vpx-job.log', 'w')
            xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
            vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
            xenrt.TEC().logverbose("ConversionVM::getlog() completed")
            vpxlog.write(vpxlogcontents)
            vpxlog.close()
            xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
            xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
            xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
            
            return

        # Get VPX log files
        vpxlog = open('/tmp/con-vpx-job.log', 'w')
        xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
        vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
        xenrt.TEC().logverbose("ConversionVM::getlog() completed")
        vpxlog.write(vpxlogcontents)
        vpxlog.close()
        xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
        xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
        xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
        
        raise xenrt.XRTFailure("ConversionVM::Test failed, getVMList() completed successfully w/ invalid VMware hostname")

class TC17908(_ConversionVM):
    #ESXi 5.0
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'esx-50-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'root'
    VMWARE_SERVERINFO['Password'] = 'xenR00T1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2k3-x64 (tools)', 'UUID': '423fd63a-9c6f-dbe1-c95c-6425000ad287', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]

class TC17884(_ConversionVM):
    """Connect using invalid VMware credentials"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)
        
        # Test invalid VMware password
        self.VMWARE_SERVERINFO['Password'] = 'foo'
        xenrt.TEC().logverbose("ConversionVM::self.VMWARE_SERVERINFO['Password'] = %s" % self.VMWARE_SERVERINFO['Password'])
        xenrt.TEC().logverbose("ConversionVM::Calling getVMList() w/ invalid VMware password")
        try:
            self.convServer.getVMList(session, vpx, self.XEN_SERVICECRED, self.VMWARE_SERVERINFO)
        except Exception, e:
            xenrt.TEC().logverbose("ConversionVM::Exception = %s" % e)
            xenrt.TEC().logverbose("ConversionVM::Test passed, getVMList() failed w/ invalid VMware password")
            # Test invalid VMware username
            self.VMWARE_SERVERINFO['Username'] = 'foo'
            xenrt.TEC().logverbose("ConversionVM::self.VMWARE_SERVERINFO['Username'] = %s" % self.VMWARE_SERVERINFO['Username'])
            xenrt.TEC().logverbose("ConversionVM::Calling getVMList() w/ invalid VMware username")
            try:
                self.convServer.getVMList(session, vpx, self.XEN_SERVICECRED, self.VMWARE_SERVERINFO)
            except Exception, e:
                xenrt.TEC().logverbose("ConversionVM::Exception = %s" % e)
                xenrt.TEC().logverbose("ConversionVM::Test passed, getVMList() failed w/ invalid VMware username")
                return
            raise xenrt.XRTFailure("ConversionVM::Test failed, getVMList() completed successfully w/ invalid VMware username")
        raise xenrt.XRTFailure("ConversionVM::Test failed, getVMList() completed successfully w/ invalid VMware password")

class TC17885(_ConversionVM):
    """Convert invalid VM name"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)

        # Test invalid VMware VM name
        xenrt.TEC().logverbose("ConversionVM::Calling createJob() w/ VMware VM name = foo")
        importInfo = {'SRuuid': ""}
        jobInfo = {'JobName': "test name", 'JobDesc': "test description", 'UserField1': ""}
        jobInfo['SourceVmName'] = 'foo'
        jobInfo['SourceVmUUID'] = ''
        jobInfo['Source'] = self.VMWARE_SERVERINFO
        jobInfo['ImportInfo'] = importInfo
        jobInfo['PreserveMAC'] = True
        xenrt.TEC().logverbose("ConversionVM::Creating Job")
        JobInstance = vpx.job.create(self.XEN_SERVICECRED, jobInfo)
        xenrt.TEC().logverbose("ConversionVM::JobInstance = %s" % JobInstance)

        JobInstance = vpx.job.get(self.XEN_SERVICECRED, JobInstance['Id'])
        while JobInstance['State'] != 3 or JobInstance['State'] != 4 or JobInstance['State'] != 5:
            JobInstance = vpx.job.get(self.XEN_SERVICECRED, JobInstance['Id'])
            xenrt.TEC().logverbose("Id = %s, State = %s, PercentComplete = %s" %
                                    (JobInstance['Id'],
                                    JobInstance['State'],
                                    JobInstance['PercentComplete'])
                                    )
            if JobInstance['State'] == 3:
                xenrt.TEC().logverbose("ConversionVM::Job completed, State = %s" % JobInstance['State'])

                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                raise xenrt.XRTFailure("ConversionVM::Test failed, createJob() completed successfully w/ VMware VM name = foo")
                
            if JobInstance['State'] == 4:
                xenrt.TEC().logverbose("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                xenrt.TEC().logverbose("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                
                xenrt.TEC().logverbose("ConversionVM::Test passed, createJob() failed w/ VMware VM name = foo")
                return
                
            if JobInstance['State'] == 5:
                xenrt.TEC().logverbose("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                xenrt.TEC().logverbose("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
                
                raise xenrt.XRTFailure("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
            
            # Sleep for 20 seconds before calling vpx.job.get() again
            time.sleep(20)
                
class TC17886(_ConversionVM):
    """Convert invalid VM UUID"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)

        # Test invalid VMware VM UUID
        xenrt.TEC().logverbose("ConversionVM::Calling createJob() w/ VMware VM UUID = foo")
        importInfo = {'SRuuid': ""}
        jobInfo = {'JobName': "test name", 'JobDesc': "test description", 'UserField1': ""}
        jobInfo['SourceVmName'] = ''
        jobInfo['SourceVmUUID'] = 'foo'
        jobInfo['Source'] = self.VMWARE_SERVERINFO
        jobInfo['ImportInfo'] = importInfo
        jobInfo['PreserveMAC'] = True
        xenrt.TEC().logverbose("ConversionVM::Creating Job")
        JobInstance = vpx.job.create(self.XEN_SERVICECRED, jobInfo)
        xenrt.TEC().logverbose("ConversionVM::JobInstance = %s" % JobInstance)

        JobInstance = vpx.job.get(self.XEN_SERVICECRED, JobInstance['Id'])
        while JobInstance['State'] != 3 or JobInstance['State'] != 4 or JobInstance['State'] != 5:
            JobInstance = vpx.job.get(self.XEN_SERVICECRED, JobInstance['Id'])
            xenrt.TEC().logverbose("Id = %s, State = %s, PercentComplete = %s" %
                                    (JobInstance['Id'],
                                    JobInstance['State'],
                                    JobInstance['PercentComplete'])
                                    )
            if JobInstance['State'] == 3:
                xenrt.TEC().logverbose("ConversionVM::Job completed, State = %s" % JobInstance['State'])

                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                raise xenrt.XRTFailure("ConversionVM::Test failed, createJob() completed successfully w/ VMware VM UUID = foo")
                
            if JobInstance['State'] == 4:
                xenrt.TEC().logverbose("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                xenrt.TEC().logverbose("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                
                xenrt.TEC().logverbose("ConversionVM::Test passed, createJob() failed w/ VMware VM UUID = foo")
                return
                
            if JobInstance['State'] == 5:
                xenrt.TEC().logverbose("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                raise xenrt.XRTFailure("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
            
            # Sleep for 20 seconds before calling vpx.job.get() again
            time.sleep(20)

class TC17887(_ConversionVM):
    """Convert to invalid XenServer SR UUID"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)

        # Test invalid XenServer SR UUID
        xenrt.TEC().logverbose("ConversionVM::Calling createJob() w/ XenServer SRuuid = foo")
        importInfo = {'SRuuid': "foo"}
        jobInfo = {'JobName': "test name", 'JobDesc': "test description", 'UserField1': ""}
        jobInfo['SourceVmName'] = ''
        jobInfo['SourceVmUUID'] = '423e073d-fea9-3628-2ddd-fcb05871420d'
        jobInfo['Source'] = self.VMWARE_SERVERINFO
        jobInfo['ImportInfo'] = importInfo
        jobInfo['PreserveMAC'] = True
        xenrt.TEC().logverbose("ConversionVM::Calling job.create() w/ invalid XenServer SRuuid")

        try:
            JobInstance = vpx.job.create(self.XEN_SERVICECRED, jobInfo)
        except Exception, e:
            xenrt.TEC().logverbose("ConversionVM::Exception = %s" % e)
            xenrt.TEC().logverbose("ConversionVM::Test passed, create() failed w/ invalid XenServer SRuuid")
            
            # Get VPX log files
            vpxlog = open('/tmp/con-vpx-job.log', 'w')
            xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
            vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
            xenrt.TEC().logverbose("ConversionVM::getlog() completed")
            vpxlog.write(vpxlogcontents)
            vpxlog.close()
            xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
            xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
            xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
            
            return
            
        # Get VPX log files
        vpxlog = open('/tmp/con-vpx-job.log', 'w')
        xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
        vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
        xenrt.TEC().logverbose("ConversionVM::getlog() completed")
        vpxlog.write(vpxlogcontents)
        vpxlog.close()
        xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
        xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
        xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
        
        raise xenrt.XRTFailure("ConversionVM::Test failed, getVMList() completed successfully w/ invalid XenServer SRuuid")
        
class TC17888(_ConversionVM):
    """Get invalid job number"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)

        # Test invalid job number
        xenrt.TEC().logverbose("ConversionVM::Calling job.get() w/ invalid job number")
        try:
            vpx.job.get(self.XEN_SERVICECRED, "foo")
        except Exception, e:
            xenrt.TEC().logverbose("ConversionVM::Exception = %s" % e)
            xenrt.TEC().logverbose("ConversionVM::Test passed, job.get() failed w/ invalid job number")
            
            # Get VPX log files
            vpxlog = open('/tmp/con-vpx-job.log', 'w')
            xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
            vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
            xenrt.TEC().logverbose("ConversionVM::getlog() completed")
            vpxlog.write(vpxlogcontents)
            vpxlog.close()
            xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
            xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
            xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
            
            return
            
        # Get VPX log files
        vpxlog = open('/tmp/con-vpx-job.log', 'w')
        xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
        vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
        xenrt.TEC().logverbose("ConversionVM::getlog() completed")
        vpxlog.write(vpxlogcontents)
        vpxlog.close()
        xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
        xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
        xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
        
        raise xenrt.XRTFailure("ConversionVM::Test failed, job.get() completed successfully w/ invalid job number")
        
class TC17889(_ConversionVM):
    """Cancel a running job"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)

        # Create job
        xenrt.TEC().logverbose("ConversionVM::Calling createJob()")
        importInfo = {'SRuuid': ""}
        jobInfo = {'JobName': "test name", 'JobDesc': "test description", 'UserField1': ""}
        jobInfo['SourceVmName'] = ''
        jobInfo['SourceVmUUID'] = '423edfb4-2ea5-9493-1afe-588b7f235e44'
        jobInfo['Source'] = self.VMWARE_SERVERINFO
        jobInfo['ImportInfo'] = importInfo
        jobInfo['PreserveMAC'] = True
        xenrt.TEC().logverbose("ConversionVM::Creating Job")
        JobInstance = vpx.job.create(self.XEN_SERVICECRED, jobInfo)
        xenrt.TEC().logverbose("ConversionVM::JobInstance = %s" % JobInstance)

        JobInstance = vpx.job.get(self.XEN_SERVICECRED, JobInstance['Id'])
        while JobInstance['State'] != 3 or JobInstance['State'] != 4 or JobInstance['State'] != 5:
            JobInstance = vpx.job.get(self.XEN_SERVICECRED, JobInstance['Id'])
            xenrt.TEC().logverbose("Id = %s, State = %s, PercentComplete = %s" %
                                    (JobInstance['Id'],
                                    JobInstance['State'],
                                    JobInstance['PercentComplete'])
                                    )
            # Cancel job
            if JobInstance['PercentComplete'] > 25:
                xenrt.TEC().logverbose("ConversionVM::Job running, State = %s" % JobInstance['State'])
                vpx.job.delete(self.XEN_SERVICECRED, JobInstance['Id'])
            
            if JobInstance['State'] == 3:
                xenrt.TEC().logverbose("ConversionVM::Job completed, State = %s" % JobInstance['State'])

                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                raise xenrt.XRTFailure("ConversionVM::Test failed, job was not cancelled")
                
            if JobInstance['State'] == 4:
                xenrt.TEC().logverbose("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                raise xenrt.XRTFailure("ConversionVM::Job Aborted, State = %s" % JobInstance['State'])
                
            if JobInstance['State'] == 5:
                xenrt.TEC().logverbose("ConversionVM::Job User Aborted, State = %s" % JobInstance['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                xenrt.TEC().logverbose("ConversionVM::Test passed, job.delete() completed successfully")
                return
            
            # Sleep for 20 seconds before calling vpx.job.get() again
            time.sleep(20)

class TC18009(_ConversionVM):
    """Cancel a queued job"""
    XEN_SERVICECRED = {'Username': 'root', 'Password': xenrt.TEC().lookup("ROOT_PASSWORD")}
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'

    def run(self, arglist=None):
        self.convServerName = self.CONVSERVER_NAME
        self.host = self.getDefaultHost()
        g = self.host.guestFactory()(self.convServerName, "NO_TEMPLATE", password=xenrt.TEC().lookup("DEFAULT_PASSWORD"))
        self.convServer = xenrt.ConversionApplianceServer(g)

        # Detect VPX
        xenrt.TEC().logverbose("ConversionVM::Checking for Conversion VPX")
        existing_vpx = self.host.execdom0("xe vm-list params=other-config | grep conversionvm", retval="code")
        if existing_vpx == 1:
            raise xenrt.XRTError("ConversionVM::Conversion VPX not found")
        xenrt.TEC().logverbose("ConversionVM::Conversion VPX found")

        # Check VPX
        url = "https://%s" % self.host.getIP()
        xenrt.TEC().logverbose("ConversionVM::XenServer IP = %s" % self.host.getIP())
        session = XenAPI.Session(url)
        session.xenapi.login_with_password("root", self.host.password)
        xenrt.TEC().logverbose("ConversionVM::Calling getVpx()")
        vpx = self.convServer.getVpx(session)
        xenrt.TEC().logverbose("ConversionVM::getVpx() succeeded")
        xenrt.TEC().logverbose("ConversionVM::Calling get_version()")
        vpx_version = vpx.svc.get_version()
        xenrt.TEC().logverbose("ConversionVM::VPX Version = %s" % vpx_version)

        importInfo = {'SRuuid': ""}
        jobInfo = {'JobName': "test name", 'JobDesc': "test description", 'UserField1': ""}
        jobInfo['SourceVmName'] = ''
        jobInfo['SourceVmUUID'] = '423edfb4-2ea5-9493-1afe-588b7f235e44'
        jobInfo['Source'] = self.VMWARE_SERVERINFO
        jobInfo['ImportInfo'] = importInfo
        jobInfo['PreserveMAC'] = True
        
        # Create first job
        xenrt.TEC().logverbose("ConversionVM::Creating first job")
        JobOne = vpx.job.create(self.XEN_SERVICECRED, jobInfo)
        xenrt.TEC().logverbose("ConversionVM::JobOne = %s" % JobOne)
        
        # Create second job
        jobInfo['SourceVmUUID'] = '423ea8f1-77a9-eeb6-ebea-52fdd19af5b5'
        xenrt.TEC().logverbose("ConversionVM::Creating second job")
        JobTwo = vpx.job.create(self.XEN_SERVICECRED, jobInfo)
        xenrt.TEC().logverbose("ConversionVM::JobTwo = %s" % JobTwo)
        
        # Monitor jobs
        while JobOne['State'] != 3 or JobOne['State'] != 4 or JobOne['State'] != 5:
            JobOne = vpx.job.get(self.XEN_SERVICECRED, JobOne['Id'])
            JobTwo = vpx.job.get(self.XEN_SERVICECRED, JobTwo['Id'])
            xenrt.TEC().logverbose("Id = %s, State = %s, PercentComplete = %s" %
                                    (JobOne['Id'],
                                    JobOne['State'],
                                    JobOne['PercentComplete'])
                                    )
            xenrt.TEC().logverbose("Id = %s, State = %s, PercentComplete = %s" %
                                    (JobTwo['Id'],
                                    JobTwo['State'],
                                    JobTwo['PercentComplete'])
                                    )
            if JobOne['PercentComplete'] > 25 and JobTwo['State'] == 1:
                xenrt.TEC().logverbose("ConversionVM::Job queued, State = %s" % JobTwo['State'])
                vpx.job.delete(self.XEN_SERVICECRED, JobTwo['Id'])
                
            if JobTwo['State'] == 3:
                xenrt.TEC().logverbose("ConversionVM::Job completed, State = %s" % JobTwo['State'])

                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                raise xenrt.XRTFailure("ConversionVM::Test failed, job was not cancelled")
                
            if JobTwo['State'] == 4:
                xenrt.TEC().logverbose("ConversionVM::Job Aborted, State = %s" % JobTwo['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                raise xenrt.XRTFailure("ConversionVM::Job Aborted, State = %s" % JobTwo['State'])
                
            if JobTwo['State'] == 5:
                xenrt.TEC().logverbose("ConversionVM::Job User Aborted, State = %s" % JobTwo['State'])
                
                # Get VPX log files
                vpxlog = open('/tmp/con-vpx-job.log', 'w')
                xenrt.TEC().logverbose("ConversionVM::Calling getlog()")
                vpxlogcontents = vpx.svc.getlog(self.XEN_SERVICECRED)
                xenrt.TEC().logverbose("ConversionVM::getlog() completed")
                vpxlog.write(vpxlogcontents)
                vpxlog.close()
                xenrt.TEC().logverbose("ConversionVM::Calling copyToLogDir()")
                xenrt.TEC().copyToLogDir('/tmp/con-vpx-job.log')
                xenrt.TEC().logverbose("ConversionVM::copyToLogDir() completed")
                
                xenrt.TEC().logverbose("ConversionVM::Test passed, job.delete() completed successfully")
                vpx.job.delete(self.XEN_SERVICECRED, JobOne['Id'])
                return
            
            # Sleep for 20 seconds before calling vpx.job.get() again
            time.sleep(20)

class TC18142(_ConversionVM):
    """Convert valid VM name"""
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x64 (tools)', 'UUID': '', 'WINDOWS': True, 'DISTRO': "w2k3eesp2-x64"}]
    
# ESXi 4.1 Linux (no tools)
class TC18385(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-10.04-LTS-x86 (thin)', 'UUID': '4217e19c-a92f-b596-346b-9adb88ad3ccb', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18386(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-10.04-LTS-x64 (thin)', 'UUID': '421718c0-4a15-cd5c-0f0f-d50dae443887', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18390(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-12.04-LTS-x86 (thin)', 'UUID': '42172258-da47-6deb-66d3-a08aa7863809', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18389(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-12.04-LTS-x64 (thin)', 'UUID': '42174b0a-3d0a-84a7-133f-64d43780c58d', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18406(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-5.0.4-x86 (thin)', 'UUID': '42173826-080b-c8a3-4eea-2f9369eb89d8', 'WINDOWS': False, 'DISTRO': "debian50"}]

class TC18407(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-5.0.10-x64 (thin)', 'UUID': '4217e6cf-cee2-faac-d405-9eb50b6c6bf4', 'WINDOWS': False, 'DISTRO': "debian50"}]

class TC18398(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-6-x86 (thin)', 'UUID': '42174fa7-b92e-f03f-615a-22412da0f3da', 'WINDOWS': False, 'DISTRO': "debian60"}]

class TC18399(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-6-x64 (thin)', 'UUID': '4217b429-9447-b01b-7430-eb65b14512a0', 'WINDOWS': False, 'DISTRO': "debian60"}]

class TC18403(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-centos-5.4-x86 (thin)', 'UUID': '42177fa4-996c-a11a-de0a-514f3259cd59', 'WINDOWS': False, 'DISTRO': "centos54"}]

class TC18402(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-centos-5.4-x64 (thin)', 'UUID': '42173c32-70c5-4317-237b-c4571bfb28c7', 'WINDOWS': False, 'DISTRO': "centos54"}]

class TC18444(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-sles-11-x86 (thin)', 'UUID': '42171cb2-bcbf-d4d0-219f-d85486e108dd', 'WINDOWS': False, 'DISTRO': "sles11"}]

class TC18445(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-sles-11-x64 (thin)', 'UUID': '4217c0b4-adda-1569-a9e7-8a7b0aee7359', 'WINDOWS': False, 'DISTRO': "sles11"}]

# ESXi 4.1 Linux (with tools)
class TC18387(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-10.04-LTS-x86 (tools)', 'UUID': '42173021-746c-f543-3f94-ebc61412bf44', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18388(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-10.04-LTS-x64 (tools)', 'UUID': '4217d053-3f3c-5270-f684-38fc69de7938', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18391(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-12.04-LTS-x86 (tools)', 'UUID': '42172360-ff6a-1d02-235f-935d3f6d65c1', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18392(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-ubuntu-12.04-LTS-x64 (tools)', 'UUID': '421741b3-5cf5-d41c-b915-7e00608014dd', 'WINDOWS': False, 'DISTRO': "ubuntu1004"}]

class TC18441(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-5.0.4-x86 (tools)', 'UUID': '4217d246-5180-9ca6-0446-23436401d694', 'WINDOWS': False, 'DISTRO': "debian50"}]

class TC18442(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-5.0.10-x64 (tools)', 'UUID': '421701c5-15e8-4e58-6566-1c0f688bfff1', 'WINDOWS': False, 'DISTRO': "debian50"}]

class TC18400(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-6-x86 (tools)', 'UUID': '42173b57-2025-ee69-ee32-39a03e45c218', 'WINDOWS': False, 'DISTRO': "debian60"}]

class TC18401(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-debian-6-x64 (tools)', 'UUID': '42176940-5532-6a13-27a7-a6d0484dd3ad', 'WINDOWS': False, 'DISTRO': "debian60"}]

class TC18404(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-centos-5.4-x86 (tools)', 'UUID': '42174175-f37e-4d10-d931-71f6442f8c98', 'WINDOWS': False, 'DISTRO': "centos54"}]

class TC18405(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esx41-centos-5.4-x64 (tools)', 'UUID': '421703ca-4c28-f5b0-b396-09b1c024ba78', 'WINDOWS': False, 'DISTRO': "centos54"}]

class TC18497(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-01.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi41-win2k3-x86 (tools)', 'UUID': '423ea8f1-77a9-eeb6-ebea-52fdd19af5b5', 'WINDOWS': True, 'DISTRO': "w2k3eesp2"}]
    HOSTS = 2
    #NFSSERVER = "[NFS server]"
    #NFSSERVERPATH = "[NFS server path]"

class TC20608(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win2012-x64 (tools)', 'UUID': '4202c18d-abf7-02c9-6298c-4d6e2c839c6', 'WINDOWS': True, 'DISTRO': "ws12-x64"}]

class TC20609(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win8-x64 (tools)', 'UUID': '4202ab0f-f3aa-286a-746a9-d1d4504496b', 'WINDOWS': True, 'DISTRO': "win8-x64"}]

class TC20610(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win8-x86 (tools)', 'UUID': '420224b6-ece2-0fac-4dc0a-73bf192f5fa', 'WINDOWS': True, 'DISTRO': "win8-x86"}]

class TC20611(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win81-x64 (tools)', 'UUID': '42025c79-db78-7758-528d8-d6842416cec', 'WINDOWS': True, 'DISTRO': "win81-x64"}]

class TC20612(_ConversionVM):
    VMWARE_SERVERINFO = {'ServerType': 2}
    VMWARE_SERVERINFO['Hostname'] = 'vcenter-rdm-04.ad.xensource.com'
    VMWARE_SERVERINFO['Username'] = 'administrator'
    VMWARE_SERVERINFO['Password'] = 'xenROOT1'
    VMLIST = [ {'VMWAREVM': 'esxi50-win81-x86 (tools)', 'UUID': '4202dbe4-3099-b263-9d191-c796362b814', 'WINDOWS': True, 'DISTRO': "win81-x86"}]
