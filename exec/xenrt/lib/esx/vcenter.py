
#
# XenRT: Test harness for Xen and the XenServer product family
#
# Operations on ESX hosts.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#


import csv, os, re, string, StringIO, random, threading
import xenrt

__all__ = ["getVCenter"]

_vcenter = None

class VCenter(object):
    def __init__(self, guest=None, vCenterVersion="5.5.0-update02"):

        self.lock = threading.RLock()
        self.username = xenrt.TEC().lookup(["VCENTER","USERNAME"])
        self.password = xenrt.TEC().lookup(["VCENTER","PASSWORD"])
        self.useWinrm = xenrt.TEC().lookup(["VCENTER","WINRM_ENABLED"], False, boolean=True)
        self.guest=guest

        if not guest:
            self._loadGlobalVCenter()
        else:
            self._setupVCenter(guest=guest, vCenterVersion=vCenterVersion)

        self.dvs = "no"
        if xenrt.TEC().lookup("VMWARE_DVS", False, boolean=True):
            xenrt.TEC().warning("Check for VMware DVS")
            self.dvs = "yes"

        if xenrt.TEC().lookup("CMD_VIA_WINRM", True, boolean=True):
            xenrt.TEC().warning("Enforcing cmdExec via WinRM")
            self.vc.os.enableWinRM()
            self.useWinrm = True

    def _setupVCenter(self, guest, vCenterVersion="5.5.0-update02"):
        self.address = guest.mainip
        self.vCenterVersion = vCenterVersion
        self.vc = xenrt.lib.generic.StaticOS(guest.distro, guest.mainip)
        self.vc.os.enablePowerShellUnrestricted()
        self.vc.os.ensurePackageInstalled("PowerShell 3.0")
        self.vc.os.enableWinRM()
        self.vc.os.sendRecursive("%s/data/tests/vmware" % xenrt.TEC().lookup("XENRT_BASE"), "c:\\vmware")

        if not self.isVCenterInstalled():
            self._installVCenter()

    def _installVCenter(self):
        isoUrl=xenrt.TEC().lookup(["VCENTER","ISO","_%s" % self.vCenterVersion.upper()])
        isoName = isoUrl.rsplit("/",1)[1]
        if isoName not in self.guest.host.findISOs():
            srPath = None
            isoPath=xenrt.TEC().getFile(isoUrl)
            isoPath = xenrt.command("readlink -f %s" % isoPath).strip()
            if xenrt.command("stat --file-system --format=%%T %s" % isoPath).strip()=="nfs":
                nfsMountInfo=xenrt.command("df %s" % isoPath).strip().split("\n")[-1].split(" ")
                # nfsMountInfo will look like ['10.220.254.45:/vol/xenrtdata/cache', '2147483648', '1678503168', '468980480', '', '79%', '/misc/cache_nfs']
                srPath=isoPath.rsplit("/",1)[0].replace(nfsMountInfo[-1], nfsMountInfo[0])
            else:
                ip=xenrt.command("/sbin/ifconfig eth0 | grep 'inet addr' | awk -F: '{print $2}' | awk '{print $1}'" ).strip()
                srPath=ip+":"+isoPath.rsplit("/",1)[0]
            self.guest.host.createISOSR(srPath)

        self.guest.changeCD(isoName)
        xenrt.sleep(30)

        if "ws12" in self.guest.distro and "5.5" in self.vCenterVersion:
            self._installVCenter55onWs12()
        else:
            raise xenrt.XRTError("Unimplemented")
        self.guest.changeCD(None)

        self._installpowerCLI()

    def _installVCenter55onWs12(self):

        # Get DVD Drive letter
        command="Get-WmiObject win32_logicaldisk -filter 'DriveType=5 and Access>0' | ForEach-Object {$_.DeviceID}"
        driveLetter = self.guest.xmlrpcExec(command, returndata=True, powershell=True, ignoreHealthCheck=True).strip().split("\n")[-1].strip(" :")

        # Single Sign On
        command='''start /wait msiexec.exe /i "%s:\\Single Sign-On\\VMware-SSO-Server.msi" /qr \
ADMINPASSWORD=%s \
SSO_SITE=mysite \
/l*v %%TEMP%%\\vim-sso-msi.log ''' % (driveLetter, self.password)
        self.guest.addExtraLogFile("%TEMP%\\vim-sso-msi.log")
        self.guest.xmlrpcExec(command, timeout=1800)

        # Inventory Service
        command='''start /wait %s:\\"Inventory Service"\\VMware-inventory-service.exe /S /v" \
SSO_ADMIN_PASSWORD=\"%s\" \
LS_URL=\"https://%s:7444/lookupservice/sdk\" \
TOMCAT_MAX_MEMORY_OPTION=S \
/L*V \"%%temp%%\\vim-qs-msi.log\" /qr" ''' % (driveLetter, self.password, self.guest.mainip)
        self.guest.addExtraLogFile("%TEMP%\\vim-qs-msi.log")
        self.guest.xmlrpcExec(command, timeout=1800)

        # Vcenter Server
        command='''start /wait %s:\\vCenter-Server\\VMware-vcserver.exe /S /v" \
DB_SERVER_TYPE=Bundled \
FORMAT_DB=1 \
SSO_ADMIN_USER=\"%s\" \
SSO_ADMIN_PASSWORD=\"%s\" \
LS_URL=\"https://%s:7444/lookupservice/sdk\" \
IS_URL=\"https://%s:10443/\" \
VC_ADMIN_USER=administrator@vsphere.local \
/L*v \"%%TEMP%%\\vmvcsvr.log\" /qr" ''' % (driveLetter, self.username, self.password, self.guest.mainip, self.guest.mainip)
        self.guest.addExtraLogFile("%TEMP%\\vmvcsvr.log")
        self.guest.xmlrpcExec(command, timeout=3600)

        # vSphere Client
        command='''start /wait %s:\\vSphere-Client\\VMware-viclient.exe /S /v" \
/L*v \"%%TEMP%%\\vim-vic-msi.log\" /qr" ''' % (driveLetter)
        self.guest.addExtraLogFile("%TEMP%\\vim-vic-msi.log")
        self.guest.xmlrpcExec(command, timeout=3600)

        # vSphere WebClient
        command='''start /wait %s:\\vSphere-WebClient\\VMware-WebClient.exe /S /v" \
SSO_ADMIN_USER=\"%s\" \
SSO_ADMIN_PASSWORD=\"%s\" \
LS_URL=\"https://%s:7444/lookupservice/sdk\" \
/L*v \"%%TEMP%%\\vim-ngc-msi.log\" /qr" ''' % (driveLetter, self.username, self.password, self.guest.mainip)
        self.guest.addExtraLogFile("%TEMP%\\vim-ngc-msi.log")
        self.guest.xmlrpcExec(command, timeout=1800)

    def _installpowerCLI(self):
        # vSphere PowerCLI
        installerFileURL = xenrt.TEC().lookup(["VCENTER","POWERCLI",xenrt.TEC().lookup("VSPHERE_POWERCLI_VERSION", "DEFAULT")])
        installerFileName = installerFileURL.rsplit("/",1)[1]
        self.guest.xmlrpcFetchFile(installerFileURL, "C:\\%s" % installerFileName )

        command='''C:\\%s /q /s /w /V" /L*v \"%%TEMP%%\\vm-powercli.log\" /qr" ''' % (installerFileName)
        self.guest.addExtraLogFile("%TEMP%\\vm-powercli.log")
        self.guest.xmlrpcExec(command, timeout=1800)

    def execPowerCLI(self,
                    command,
                    level=xenrt.RC_FAIL,
                    desc="PowerCLI Remote command",
                    returndata=False,
                    returnerror=True,
                    returnrc=False,
                    timeout=300,
                    ignoredata=False,
                    ignoreHealthCheck=False):
        """Execute a powercli command and wait for completion."""
        pwrCliCmd  = r"""Add-PSSnapIn vm* """
        pwrCliCmd += "\n" + r"""Connect-ViServer -Server %s -User %s -Password %s """ % (self.address, self.username, self.password)
        pwrCliCmd += "\n" + r"""echo "XenRT Output:" """
        pwrCliCmd += "\n" + command
        data = self.vc.os.cmdExec(pwrCliCmd,
                            level=level,
                            desc=desc,
                            returndata=returndata,
                            returnerror=returnerror,
                            returnrc=returnrc,
                            timeout=timeout,
                            ignoredata=ignoredata,
                            powershell=True,
                            winrm=self.useWinrm,
                            ignoreHealthCheck=ignoreHealthCheck)
        if returndata:
            data = data.split("XenRT Output:")[-1].strip()
            # Remove extra whitespaces/lines
            return re.sub(r'(?<=\S)\s*\n(?=\S)',"\n", data)
        else:
            return data

    def isVCenterInstalled(self):
        services = self.vc.os.cmdExec("get-service -displayname VMware* | where-object {$_.Status -eq 'Running'}", returndata=True, powershell=True, winrm=self.useWinrm).strip()
        if "VMware VirtualCenter Server" in services:
            return True
        return False

    def _loadGlobalVCenter(self):
        vccfg = xenrt.TEC().lookup("VCENTER")
        self.vc = xenrt.lib.generic.StaticOS(vccfg['DISTRO'], vccfg['ADDRESS'])
        self.vc.os.enablePowerShellUnrestricted()
        self.vc.os.ensurePackageInstalled("PowerShell 3.0")
        self.vc.os.sendRecursive("%s/data/tests/vmware" % xenrt.TEC().lookup("XENRT_BASE"), "c:\\vmware")
        self.vc.os.password = "xenroot01T"
        self.username = vccfg['USERNAME']
        self.address = vccfg['ADDRESS']
        self.password = vccfg['PASSWORD']

    def addHost(self, host, dc, cluster):
        with self.lock:
            xenrt.TEC().logverbose(self.vc.os.cmdExec("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\addhost.ps1 %s %s %s %s %s %s %s %s %s" % (
                                                        self.address,
                                                        self.username,
                                                        self.password,
                                                        dc,
                                                        cluster,
                                                        host.getIP(),
                                                        "root",
                                                        host.password,
                                                        self.dvs), returndata=True, winrm=self.useWinrm))
               

            hostlist =csv.DictReader(StringIO.StringIO(self.vc.os.readFile("c:\\vmware\\%s.csv" % dc)))
            self.vc.os.removeFile("c:\\vmware\\%s.csv" % dc)
            try:
                myhost = [x for x in hostlist if x['Name'] == host.getIP()][0]
            except:
                raise xenrt.XRTError("Host not added to vCenter")

            # If the host hasn't got a license, it will just contain 0s and dashes, so we need to license it
            if not myhost['LicenseKey'].replace("-", "").replace("0",""):
                # Now get the list of licenses

                self.vc.os.cmdExec("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\listlicenses.ps1 %s %s %s" % (
                                        self.address,
                                        self.username,
                                        self.password), winrm=self.useWinrm)


                liclist =csv.DictReader(StringIO.StringIO(self.vc.os.readFile("c:\\vmware\\licenses.csv")))

                # Filter ESX licenses
                liclist = [x for x in liclist if x['EditionKey'].startswith("esx")]

                # Filter ones with remaining capacity
                liclist = [x for x in liclist if int(x['Used']) < int(x['Total'])]

                if liclist:
                    lic = random.choice(liclist)['LicenseKey']
                    xenrt.TEC().logverbose("Using license %s" % lic)
                    xenrt.TEC().logverbose(self.vc.os.cmdExec("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\assignlicense.ps1 %s %s %s %s %s" % (
                                                                    self.address,
                                                                    self.username,
                                                                    self.password,
                                                                    host.getIP(),
                                                                    lic), returndata=True, winrm=self.useWinrm))

                     
                    hostlist =csv.DictReader(StringIO.StringIO(self.vc.os.readFile("c:\\vmware\\lic-%s.csv" % host.getIP())))
                    self.vc.os.removeFile("c:\\vmware\\lic-%s.csv" % host.getIP())
                    try:
                        myhost = [x for x in hostlist if x['Name'] == host.getIP()][0]
                    except:
                        raise xenrt.XRTError("Host not added to vCenter")

                    if myhost['LicenseKey'] != lic:
                        raise xenrt.XRTError("Host not licensed with correct key - expected %s, found %s" % (lic, myhost['LicenseKey']))

                else:
                    xenrt.TEC().logverbose("No VMWare Licenses available, continuing in evaluation mode")

    def listDataCenters(self):
        with self.lock:
            self.vc.os.cmdExec("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\listdatacenters.ps1 %s %s %s" % (
                                    self.address,
                                    self.username,
                                    self.password))


            dclist =csv.DictReader(StringIO.StringIO(self.vc.os.readFile("c:\\vmware\\dc.csv")))
            return [x['Name'] for x in dclist]

    def removeDataCenter(self, dc):
        with self.lock:
            xenrt.TEC().logverbose(self.vc.os.cmdExec("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\removedatacenter.ps1 %s %s %s %s" % (
                                                        self.address,
                                                        self.username,
                                                        self.password,
                                                        dc), returndata=True, winrm=self.useWinrm))

    def removeHost(self, host):
        # TODO - remove only host and not complete datacenter, if datacenter has more hosts in it. Same applies for cluster.
        self.removeDataCenter(host.datacenter)

def getVCenter(guest=None, vCenterVersion="5.5.0-update02"):
    if not guest:
        global _vcenter
        with xenrt.GEC().getLock("VCENTER"):
            if not _vcenter:
                _vcenter = VCenter()
        return _vcenter
    else:
        return VCenter(guest=guest, vCenterVersion=vCenterVersion)
