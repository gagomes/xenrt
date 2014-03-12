
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer Storage Certification (XenCert) Kit - Standalone testcases
#
# Copyright (c) 2013 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, xml.dom.minidom,time,re,os

class _XSStorageCertKit(xenrt.TestCase):
    """Base class for XenServer Storage Certification Kit"""

    XENCERT_ISO = "xencert-supp-pack.iso"
    XENCERT_RPMS = ["xencert-1.8.50-xs10", "xenserver-transfer-vm"]
    XENCERT_RPM_REPOS = ["xs:xencert-supp-pack", "xs:xenserver-transfer-vm"]

    SR_TYPE = None
    MULTIPATHING = False
    TEST_CATEGORY = ["functional", "control", "multipath", "pool", "data", "metadata"]
    ITERATIONS = "100"
    SR_PARAM = []

    def installXSStorageCertKit(self,host):

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
            storageCertKitISO = xenrt.TEC().getFile("xe-phase-2/%s" % (self.XENCERT_ISO),self.XENCERT_ISO)
        
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

        for rpm in self.XENCERT_RPMS:
            rpmInstalled = self.checkXSStorageCertKitRPMS(host,rpm)
            if not rpmInstalled:
                raise xenrt.XRTFailure("XenServer Storage Cert Kit RPM package %s is not installed" %
                                       (rpm))

        for rpmRepo in self.XENCERT_RPM_REPOS:
            rpmReposInstalled = self.checkInstalledXSStorageCertKitRepos(host,rpmRepo)
            if not rpmReposInstalled:
                raise xenrt.XRTFailure("XenServer Storage Cert Kit entries not found under installed-repos: %s" %
                                       (rpm))

    def checkInstalledXSStorageCertKitRepos(self, host, rpmRepo):
        # Check XenServer Storage Cert Kit entry exists under installed-repos
        try:
            data = host.execdom0("ls /etc/xensource/installed-repos/")
        except:
            return False
        if not rpmRepo in data:
            return False
        else:
            return True

    def checkXSStorageCertKitRPMS(self,host,rpm):
        # Check if the pack's rpms are installed
        try:
            data = host.execdom0("rpm -qi %s" % rpm)
        except:
            return False
        if "is not installed" in data:
            return False
        else:
            return True

    def storageXenResults(self):
        pass

    def waitForFinish(self):
        pass

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        # Download and perform XenServer Storage Cert Kit installation on all hosts in the pool
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

    def multipathVerification(self):
        """Perform multipath configuration verification tests"""

        argList = []
        if not self.MULTIPATHING:
            xenrt.TEC().warning("Multipathing tests are not applicable to this particular storage")
        else:
            argList.append("-m")
            argList.extend(self.SR_PARAM)
            
            argList.append("-g")
            argList.append(self.ITERATIONS)
            
            if self.SR_TYPE == "lvmoiscsi":
                argList.append("-u")
                argList.append("/opt/xensource/debug/XenCert/blockunblockiscsipaths")
                self.runStorageXenCert(argList)
                
            if self.SR_TYPE == "lvmohba":
                try:
                    cli = self.pool.master.getCLIInstance()
                    data = cli.execute("sr-probe type=lvmohba").strip()
                except xenrt.XRTFailure, e:
                    # Split away the stuff before the <?xml
                    split = e.data.split("<?",1)
                    if len(split) != 2:
                        raise xenrt.XRTFailure("Couldn't find XML output from "
                                               "sr-probe command")
                    data = "<?" + split[1]
                # Parse the XML and check each LUN
                dom = xml.dom.minidom.parseString(data)
                adapters = dom.getElementsByTagName("Adapter")
                if len(adapters) == 0:
                    raise xenrt.XRTFailure(\
                        "There no fibre channel adapters installed on the server")
                for a in adapters:
                    temp = []
                    pathInfo= []
                    hostids = a.getElementsByTagName("host")
                    hostid = hostids[0].childNodes[0].data.strip()
                    names = a.getElementsByTagName("name")
                    name = names[0].childNodes[0].data.strip()

                    if (name == "qlogic"):
                        pathInfo.append("-u /opt/xensource/debug/XenCert/blockunblockhbapaths-qlogic")
                    elif (name == "brocade"):
                        pathInfo.append("-u /opt/xensource/debug/XenCert/blockunblockhbapaths-brocade")
                    elif (name == "cisco"):
                        pathInfo.append("-u /opt/xensource/debug/XenCert/blockunblockhbapaths-cisco")
                    else :
                        xenrt.TEC().warning("New Adapter found %s " %(name))
                    
                    try:
                        portName = self.pool.master.execdom0("systool -c fc_host -A port_name -d %s | grep port_name" % hostid).strip().split("=")[1].strip().split('"')[1]
                    except:
                        continue
                    
                    pathInfo.append("-i")
                    pathInfo.append("%s:%s" %(hostid, portName))
                    temp = argList
                    temp.extend(pathInfo)
                    self.runStorageXenCert(temp)

    def poolVerification(self):
        """Perform pool verification tests"""

        argList = []
        argList.append("-o")
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
            xenrt.TEC().warning("Metadata tests are not applicable to this particular storage")
        else:
            argList.append("-M")
            argList.extend(self.SR_PARAM)
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
        
        res = self.pool.master.execdom0("/usr/bin/python -u /opt/xensource/debug/XenCert/XenCert %s" % ' '.join(params),retval="code" ,timeout=3600)
        # obtain the resulting XenCert logs
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
            self.runSubcase("functionalVerification", (), "StorageCertKit", "functionalVerification")


        if "control" in self.TEST_CATEGORY:
            self.runSubcase("controlpathVerification", (), "StorageCertKit", "controlpathVerification")


        if "multipath" in self.TEST_CATEGORY:
            self.runSubcase("multipathVerification", (), "StorageCertKit", "multipathVerification")

        if "pool" in self.TEST_CATEGORY:
            self.runSubcase("poolVerification", (), "StorageCertKit", "poolVerification")


        if "data" in self.TEST_CATEGORY:
            self.runSubcase("dataVerification", (), "StorageCertKit", "dataVerification")


        if "metadata" in self.TEST_CATEGORY:
            self.runSubcase("metadataVerification", (), "StorageCertKit", "metadataVerification")



    def setStorageType(self, srType):
        """Sets the required SR type for the test."""
        
        # -n server                      [required] server name/IP addr
        # -e serverpath                  [required] exported path

        # -t target                      [required] comma separated list of Target names/IP addresses
        # -q targetIQN                   [required] comma separated list of target IQNs OR "*"
        # -s SCSIid                      [optional] SCSIid to use for SR creation
        # -x chapuser                    [optional] username for CHAP
        # -w chappasswd                  [optional] password for CHAP

        # -a adapters                    [optional] comma separated list of HBAs to test against

        # -b storage_type                [required] storage type (lvmoiscsi, lvmohba, nfs, isl)
        # -u pathHandlerUtil             [optional] absolute path to admin provided callout utility which blocks/unblocks a list of paths, path related information should be provided with the -i option below
        # -i pathInfo                    [optional] pass-through string used to pass data to the callout utility above, for e.g. login credentials etc. This string is passed as-is to the callout utility.
        # -g count                       [optional] count of iterations to perform in case of multipathing failover testing

        # -F file                        [required] configuration file describing target array paramters
        
        if srType == "nfs":
            self.SR_PARAM = []
            self.SR_PARAM.append("-b nfs")
            nfsConfig = xenrt.TEC().lookup("EXTERNAL_NFS_SERVERS")
            
            if not nfsConfig:
                raise xenrt.XRTError("No EXTERNAL_NFS_SERVERS defined")
            servers = nfsConfig.keys()
            if len(servers) == 0:
                raise xenrt.XRTError("No EXTERNAL_NFS_SERVERS defined")
                
            n=nfsConfig.keys()[0]
            self.SR_PARAM.append("-n %s" %xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "ADDRESS"]))
            self.SR_PARAM.append("-e %s" %xenrt.TEC().lookup(["EXTERNAL_NFS_SERVERS", n, "BASE"]))
            
        if srType == "lvmoiscsi":
            self.SR_PARAM = []
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
            for h in self.pool.slaves.values():
                h.setIQN(self.lun.getInitiatorName(allocate=True))
        
        if srType == "lvmohba":
            self.SR_PARAM = []
            self.SR_PARAM.append("-b lvmohba")
        

    def postRun(self):
        if self.SR_TYPE == "lvmoiscsi":
            self.lun.release()
    
class XSStorageCertKitNFS(_XSStorageCertKit):
    """Run the storage certification kit on NFS SR"""

    SR_TYPE = "nfs"

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

