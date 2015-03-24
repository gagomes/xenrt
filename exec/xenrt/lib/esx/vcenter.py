
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
    def __init__(self):
        self.lock = threading.RLock()
        vccfg = xenrt.TEC().lookup("VCENTER")
        self.vc = xenrt.lib.generic.StaticOS(vccfg['DISTRO'], vccfg['ADDRESS'])
        self.vc.os.enablePowerShellUnrestricted()
        self.vc.os.ensurePackageInstalled("PowerShell 3.0")
        self.vc.os.sendRecursive("%s/data/tests/vmware" % xenrt.TEC().lookup("XENRT_BASE"), "c:\\vmware")
        self.username = vccfg['USERNAME']
        self.address = vccfg['ADDRESS']
        self.password = vccfg['PASSWORD']
        self.dvs = "no"

        if xenrt.TEC().lookup("VMWARE_DVS", False, boolean=True):
            xenrt.TEC().warning("Check for VMware DVS")
            self.dvs = "yes"

    def addHost(self, host, dc, cluster):
        with self.lock:
            xenrt.TEC().logverbose(self.vc.os.execCmd("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware-j\\addhost.ps1 %s %s %s %s %s %s %s %s %s" % (
                                                        self.address,
                                                        self.username,
                                                        self.password,
                                                        dc,
                                                        cluster,
                                                        host.getIP(),
                                                        "root",
                                                        host.password,
                                                        self.dvs), returndata=True))
               

            hostlist =csv.DictReader(StringIO.StringIO(self.vc.os.readFile("c:\\vmware\\%s.csv" % dc)))
            self.vc.os.removeFile("c:\\vmware\\%s.csv" % dc)
            try:
                myhost = [x for x in hostlist if x['Name'] == host.getIP()][0]
            except:
                raise xenrt.XRTError("Host not added to vCenter")

            # If the host hasn't got a license, it will just contain 0s and dashes, so we need to license it
            if not myhost['LicenseKey'].replace("-", "").replace("0",""):
                # Now get the list of licenses

                self.vc.os.execCmd("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\listlicenses.ps1 %s %s %s" % (
                                        self.address,
                                        self.username,
                                        self.password))


                liclist =csv.DictReader(StringIO.StringIO(self.vc.os.readFile("c:\\vmware\\licenses.csv")))

                # Filter ESX licenses
                liclist = [x for x in liclist if x['EditionKey'].startswith("esx")]

                # Filter ones with remaining capacity
                liclist = [x for x in liclist if int(x['Used']) < int(x['Total'])]

                if liclist:
                    lic = random.choice(liclist)['LicenseKey']
                    xenrt.TEC().logverbose("Using license %s" % lic)
                    xenrt.TEC().logverbose(self.vc.os.execCmd("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\assignlicense.ps1 %s %s %s %s %s" % (
                                                                    self.address,
                                                                    self.username,
                                                                    self.password,
                                                                    host.getIP(),
                                                                    lic), returndata=True))

                     
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
            self.vc.os.execCmd("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\listdatacenters.ps1 %s %s %s" % (
                                    self.address,
                                    self.username,
                                    self.password))


            dclist =csv.DictReader(StringIO.StringIO(self.vc.os.readFile("c:\\vmware\\dc.csv")))
            return [x['Name'] for x in dclist]

    def removeDataCenter(self, dc):
        with self.lock:
            xenrt.TEC().logverbose(self.vc.os.execCmd("powershell.exe -ExecutionPolicy ByPass -File c:\\vmware\\removedatacenter.ps1 %s %s %s %s" % (
                                                        self.address,
                                                        self.username,
                                                        self.password,
                                                        dc), returndata=True))

def getVCenter():
    global _vcenter
    with xenrt.GEC().getLock("VCENTER"):
        if not _vcenter:
            _vcenter = VCenter()
    return _vcenter
