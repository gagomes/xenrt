# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer Storage Certification (XenCert) Kit - Standalone testcases
#
# Copyright (c) 2014 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, time, re, os

class _XSStorageCertKit(xenrt.TestCase):
    """Base class for XenServer Storage Certification Kit"""

    SR_PARAM = []
    SR_TYPE = None
    ITERATIONS = None

    MULTIPATHING = False
    FC_SWITCH_NAME = None

    XENCERT_ISO = "xencert-supp-pack.iso"
    XENCERT_RPMS = ["xencert", "xenserver-transfer-vm"]
    XENCERT_RPM_REPOS = ["xs:xencert-supp-pack", "xs:xenserver-transfer-vm"]
    TEST_CATEGORY = ["functional", "control", "multipath", "pool", "data", "metadata"]

    def installXSStorageCertKit(self,host):
        """Installs the storage XenCert Kit"""

        rpmInstalled = False
        xenrt.TEC().logverbose("Checking whether XenServer Storage Cert Kit RPMs are installed or not")
        for rpm in self.XENCERT_RPMS:
            rpmCheck = self.checkXSStorageCertKitRPMS(host,rpm)
            if not rpmCheck:
                rpmInstalled = True
                break

        reposFound = False
        xenrt.TEC().logverbose("Checking whether XenServer Storage Cert Kit REPOs are found or not")
        for rpmRepo in self.XENCERT_RPM_REPOS:
            rpmRepoCheck = self.checkInstalledXSStorageCertKitRepos(host,rpmRepo)
            if not rpmRepoCheck:
                reposFound = True
                break

        if (rpmInstalled == False and reposFound == False):
            xenrt.TEC().logverbose("XenServer Storage Cert Kit is already installed in the host.")
            return

        updatedXenCertLoc = xenrt.TEC().lookup("XENCERT_LOCATION", None)
        
        if updatedXenCertLoc != None and len(updatedXenCertLoc) > 0:
            storageCertKitISO = xenrt.TEC().getFile(updatedXenCertLoc)
        else:
            storageCertKitISO = xenrt.TEC().getFile("xe-phase-2/%s" % (self.XENCERT_ISO),self.XENCERT_ISO, "../xe-phase-2/%s" % (self.XENCERT_ISO))

        try:
            xenrt.checkFileExists(storageCertKitISO)
        except:
            raise xenrt.XRTError("XenServer Storage Cert Kit ISO not found in xe-phase-2")

        hostPath = "/tmp/%s" % (self.XENCERT_ISO)

        # Copy ISO from the controller to host in test
        sh = host.sftpClient()
        try:
            sh.copyTo(storageCertKitISO,hostPath)
        finally:
            sh.close()

        try:
            host.execdom0("xe-install-supplemental-pack /tmp/%s" % (self.XENCERT_ISO))
        except:
            xenrt.TEC().logverbose("Unable to install XenServer Storage Cert Kit")

        ignoreVersion = xenrt.TEC().lookup("IGNORE_XENCERT_VERSION", None)

        if ignoreVersion != None:
            xenrt.TEC().logverbose("XenCert version check purposely ignored")
        else:
            for rpm in self.XENCERT_RPMS:
                rpmInstalled = self.checkXSStorageCertKitRPMS(host,rpm)
                if not rpmInstalled:
                    raise xenrt.XRTFailure("XenServer Storage Cert Kit RPM package "
                                           "%s is not installed" % (rpm))

                for rpmRepo in self.XENCERT_RPM_REPOS:
                    rpmReposInstalled = self.checkInstalledXSStorageCertKitRepos(host,rpmRepo)
                    if not rpmReposInstalled:
                        raise xenrt.XRTFailure("XenServer Storage Cert Kit entries "
                                                "not found under installed-repos: %s" % (rpm))

    def checkInstalledXSStorageCertKitRepos(self, host, rpmRepo):
        """Check XenServer Storage Cert Kit entry exists under installed-repos"""

        try:
            data = host.execdom0("ls /etc/xensource/installed-repos/")
        except:
            return False
        if not rpmRepo in data:
            return False
        else:
            return True

    def checkXSStorageCertKitRPMS(self,host,rpm):
        """Check if the pack's rpms are installed"""

        try:
            data = host.execdom0("rpm -qi %s" % rpm)
        except:
            return False
        if "is not installed" in data:
            return False
        else:
            return True

    def prepare(self, arglist):

        self.pool = self.getDefaultPool()
        for h in self.pool.getHosts():
            self.installXSStorageCertKit(h)

    def functionalVerification(self):
        """Perform functional tests"""

        argList = []
        argList.append("-f")
        argList.extend(self.SR_PARAM)
        self.runStorageXenCert(argList)

    def controlpathVerification(self):
        """Perform control path tests"""

        argList = []
        argList.append("-c")
        argList.extend(self.SR_PARAM)
        self.runStorageXenCert(argList)

    def dataVerification(self):
        """perform data verification tests"""

        argList = []
        argList.append("-d")
        argList.extend(self.SR_PARAM)
        self.runStorageXenCert(argList)

    def metadataVerification(self):
        """perform metadata verification tests"""

        argList = []
        if self.SR_TYPE == "nfs" or self.SR_TYPE == "lvmohba":
            xenrt.TEC().warning("The metadata tests are not valid for NFS or HBA (are not supported or tested).")
        else:
            argList.append("-M")
            argList.extend(self.SR_PARAM)
            self.runStorageXenCert(argList)

    def poolVerification(self):
        """Perform pool verification tests"""

        argList = []
        if self.SR_TYPE == "nfs":
            xenrt.TEC().warning("The pool  tests are not valid for NFS and are not supported or tested.")
            # Refer XenCert Guide in opt/xensource/debug/XenCert/ for more info.
        else:
            argList.append("-o")
            argList.extend(self.SR_PARAM)
            self.runStorageXenCert(argList)

    def multipathVerification(self):
        """Perform multipath configuration verification tests"""

        argList = []
        if not self.MULTIPATHING:
            xenrt.TEC().warning("Multipathing tests are not applicable to this particular storage")
        else:
            argList.append("-m")
            argList.extend(self.SR_PARAM)

            if self.SR_TYPE == "lvmoiscsi":
                argList.append("-u")
                argList.append("/opt/xensource/debug/XenCert/blockunblockiscsipaths")
                self.runStorageXenCert(argList)
                
            if self.SR_TYPE == "lvmohba":
            
                switchAddr = xenrt.TEC().lookup(["FCSWITCHES", self.FC_SWITCH_NAME, 'ADDRESS'])
                if not switchAddr:
                    raise xenrt.XRTError("No IP defined for FC switch %s" % (self.FC_SWITCH_NAME))

                switchUsername =  xenrt.TEC().lookup(["FCSWITCHES", self.FC_SWITCH_NAME, 'USERNAME'])
                if not switchUsername:
                    raise xenrt.XRTError("No username defined for FC switch %s" % (self.FC_SWITCH_NAME))

                switchPasswd =  xenrt.TEC().lookup(["FCSWITCHES", self.FC_SWITCH_NAME, 'PASSWORD'])
                if not switchPasswd:
                    raise xenrt.XRTError("No password defined for FC switch %s" % (self.FC_SWITCH_NAME))

                switchType =  xenrt.TEC().lookup(["FCSWITCHES", self.FC_SWITCH_NAME, 'TYPE'])
                if not switchType:
                    raise xenrt.XRTError("No switch type defined for FC switch %s" % (self.FC_SWITCH_NAME))

                portList = []
                adapterList = []

                for h in self.pool.getHosts():

                    # find the FC switch port to which the host is connected.
                    pList = h.lookup("FCSWITCHPORTS", None).split(",")
                    if len(pList) == 0:
                        raise xenrt.XRTError("FC switch ports are not defined for host %s" % (h))
                    portList.extend(pList)

                    # find the available HBA adapters configured on the host.
                    aList = h.getHBAAdapterList() # gets you [host5,host6,host7, ...]
                    if len(aList) == 0:
                        raise xenrt.XRTError("FC adapters are not found on host %s" % (h))
                    adapterList.extend(aList)

                    # Copy the sample scripts depending on fc switch type.
                    if re.search("brocade", switchType, re.IGNORECASE):
                        h.execdom0("cp /opt/xensource/debug/XenCert/blockunblockhbapaths-brocade "
                                                        "/opt/xensource/debug/XenCert/blockunblockhbapaths")
                        h.execdom0("cp /opt/xensource/debug/XenCert/blockunblockHBAPort.sh.brocade "
                                                        "/opt/xensource/debug/XenCert/blockunblockHBAPort.sh")
                    elif re.search("cisco", switchType, re.IGNORECASE):
                        h.execdom0("cp /opt/xensource/debug/XenCert/blockunblockhbapaths-cisco "
                                                        "/opt/xensource/debug/XenCert/blockunblockhbapaths")
                        h.execdom0("cp /opt/xensource/debug/XenCert/blockunblockHBAPort.sh.cisco "
                                                        "/opt/xensource/debug/XenCert/blockunblockHBAPort.sh")
                    elif re.search("qlogic", switchType, re.IGNORECASE):
                        h.execdom0("cp /opt/xensource/debug/XenCert/blockunblockhbapaths-qlogic "
                                                        "/opt/xensource/debug/XenCert/blockunblockhbapaths")
                        h.execdom0("cp /opt/xensource/debug/XenCert/blockunblockHBAPort.sh.qlogic "
                                                        "/opt/xensource/debug/XenCert/blockunblockHBAPort.sh")

                adapterList = list(set(adapterList)) # obtain unique adapters in the pool.
                fcAdapters = string.join([adapter for adapter in adapterList], ',')
                fcSwitchPorts = string.join([port for port in portList], ',')

                xenrt.TEC().logverbose("Set of FC switch ports %s" % (fcSwitchPorts))
                xenrt.TEC().logverbose("Set of FC Adapters %s" % (fcAdapters))

                pathInfo = []
                pathInfo.append("-a")
                pathInfo.append("%s" % (fcAdapters))

                pathInfo.append("-u /opt/xensource/debug/XenCert/blockunblockhbapaths")
                pathInfo.append("-i")
                pathInfo.append("%s:%s:%s:%s" % (switchAddr, switchUsername, switchPasswd, fcSwitchPorts))

                argList.extend(pathInfo)
                self.runStorageXenCert(argList)

    def runStorageXenCert(self, params):
        """Runs the storage XenCert Kit"""

        dictTestType = {'-f':'functional-','-c':'control-','-m':'multipath-','-o':'pool-','-d':'data-','-M':'metadata-'}
        fileName = ['Xencert-']
        for key ,value in dictTestType.items():
            if key == params[0]:
                fileName.append(value)
        fileName.append(self.SR_TYPE)
        fileName.append(".log")

        res = self.pool.master.execdom0("/usr/bin/python /opt/xensource/debug/XenCert/XenCert %s" %
                                                    ' '.join(params),retval="code" ,timeout=3600)
        # Obtain the resulting XenCert logs
        xclogs = self.pool.master.execdom0("ls -t1 /tmp/XenCert-*").splitlines()
        if len(xclogs) > 0:
            data = self.pool.master.execdom0("cat %s" % xclogs[0])
            if " FAIL " in data:
                self.pool.master.addExtraLogFile(xclogs[0])
                self.pool.master.execdom0("cp %s /tmp/%s" %(xclogs[0] ,''.join(fileName)))
                self.pool.master.addExtraLogFile("/tmp/%s" %''.join(fileName)) #grab the most recent log in dom0 
                raise xenrt.XRTFailure("XenCert SR Test Suite FAILED -- See /var/log/SMlog and %s" %(''.join(fileName)))

    def run(self, arglist):

        self.setStorageType(self.SR_TYPE)

        if "functional" in self.TEST_CATEGORY:
            self.runSubcase("functionalVerification", (), "XenCertKit", "functionalVerification")
        if "control" in self.TEST_CATEGORY:
            self.runSubcase("controlpathVerification", (), "XenCertKit", "controlpathVerification")
        if "data" in self.TEST_CATEGORY:
            self.runSubcase("dataVerification", (), "XenCertKit", "dataVerification")
        if "metadata" in self.TEST_CATEGORY:
            self.runSubcase("metadataVerification", (), "XenCertKit", "metadataVerification")
        if "pool" in self.TEST_CATEGORY:
            self.runSubcase("poolVerification", (), "XenCertKit", "poolVerification")
        if "multipath" in self.TEST_CATEGORY:
            self.runSubcase("multipathVerification", (), "XenCertKit", "multipathVerification")

    def setStorageType(self, srType):
        """Sets the required SR type for the test."""

        if srType == "nfs":
            self.SR_PARAM.append("-b nfs")

            nfs = xenrt.resources.NFSDirectory()
            nfsdir = xenrt.command("mktemp -d %s/nfsXXXX" % (nfs.path()), strip = True)
            server, path = nfs.getHostAndPath(os.path.basename(nfsdir))

            self.SR_PARAM.append("-n %s" % server)
            self.SR_PARAM.append("-e %s" % path)

        if srType == "lvmoiscsi":
            self.SR_PARAM.append("-b lvmoiscsi")

            self.lun = xenrt.ISCSILun()
            self.SR_PARAM.append("-t %s" %(self.lun.getServer()))
            self.SR_PARAM.append("-q %s" %(self.lun.getTargetName()))
            self.SR_PARAM.append("-s %s" %(self.lun.getID()))
            if self.lun.chap:
                i, u, s = self.lun.chap
                self.SR_PARAM.append("-x %s" %(u))
                self.SR_PARAM.append("-w %s" %(s))
            self.pool.master.setIQN(self.lun.getInitiatorName(allocate=True))
            self.pool.master.setIQN(self.lun.getInitiatorName(allocate=True))

        if srType == "lvmohba":
            self.SR_PARAM.append("-b lvmohba")

        # if not set, default 100 iterations wil be carried out by the script.
        self.SR_PARAM.append("-g %s" % (self.ITERATIONS))

    def postRun(self):
        if self.SR_TYPE == "lvmoiscsi":
            self.lun.release()

class XSStorageCertKitNFS(_XSStorageCertKit):
    """Run the storage certification kit on NFS SR"""

    ITERATIONS = "100"
    SR_TYPE = "nfs"
    
class XSStorageCertKitNFSv4(_XSStorageCertKit):
    """Run the storage certification kit on NFSv4 SR"""

    ITERATIONS = "100"
    SR_TYPE = "nfs"
    
    def runStorageXenCert(self, params):
        """Runs the storage XenCert Kit"""

        dictTestType = {'-f':'functional-','-c':'control-','-m':'multipath-','-o':'pool-','-d':'data-','-M':'metadata-'}
        fileName = ['Xencert-']
        for key ,value in dictTestType.items():
            if key == params[0]:
                fileName.append(value)
        fileName.append(self.SR_TYPE)
        fileName.append(".log")

        res = self.pool.master.execdom0("/usr/bin/python /opt/xensource/debug/XenCert/XenCert %s" %
                                                    ' '.join(params),retval="code" ,timeout=3600)
        # Obtain the resulting XenCert logs
        xclogs = self.pool.master.execdom0("ls -t1 /tmp/XenCert-*").splitlines()
        # Check for NFSv4 in the logs
        xenrt.TEC().logverbose("Checking for NFSv4 in XenCert logs.")
        for line in xclogs:
            cg = re.search(r'(.*)Version: (\d+)', line)
            if cg and cg.group(2) != '4':
                xenrt.TEC().logverbose("Unable to test XenCert using NFSv4")
                raise xenrt.XRTFailure("Unable to test XenCert using NFSv4 -- See /var/log/SMlog and %s for more information." %(''.join(fileName)))
        if len(xclogs) > 0:
            data = self.pool.master.execdom0("cat %s" % xclogs[0])
            if " FAIL " in data:
                self.pool.master.addExtraLogFile(xclogs[0])
                self.pool.master.execdom0("cp %s /tmp/%s" %(xclogs[0] ,''.join(fileName)))
                self.pool.master.addExtraLogFile("/tmp/%s" %''.join(fileName)) #grab the most recent log in dom0 
                raise xenrt.XRTFailure("XenCert SR Test Suite FAILED -- See /var/log/SMlog and %s" %(''.join(fileName)))


class XSStorageCertKitISCSI(_XSStorageCertKit):
    """Run the storage certification kit on LVMoISCSI SR"""

    ITERATIONS = "100"
    MULTIPATHING = True
    SR_TYPE = "lvmoiscsi"

class XSStorageCertKitHBA(_XSStorageCertKit):
    """Run the storage certification kit on LVMoHBA SR"""

    ITERATIONS = "100"
    MULTIPATHING = True
    SR_TYPE = "lvmohba"
    FC_SWITCH_NAME = "XenRTFC-SVCL02-1"
