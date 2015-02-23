
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer Auto Cert Kit - Standalone testcases
#
# Copyright (c) 2011 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt, string, xml.dom.minidom,time,re,os

class _XSAutoCertKit(xenrt.TestCase):
    """Base class for XenServer Auto Cert Kit"""

    pack = "xs-auto-cert-kit.iso"
    rpms = ["xenserver-auto-cert-kit", "xenserver-transfer-vm"]
    rpmRepos = ["xs:xs-auto-cert-kit", "xs:xenserver-transfer-vm"]

    FAILTCS = []
    OPTIONALFAILTCS = []
    EXPECTERROR = False

    SINGLE_NIC = ""

    def installXSAutoCertKit(self,host):

        rpmInstalled = False
        xenrt.TEC().logverbose("Checking whether XenServer Auto Cert Kit RPMs are installed or not")
        for rpm in self.rpms:
            rpmCheck = self.checkXSAutoCertKitRPMS(host,rpm)
            if not rpmCheck:
                rpmInstalled = True
                break

        reposFound = False
        xenrt.TEC().logverbose("Checking whether XenServer Auto Cert Kit REPOs are found or not")
        for rpmRepo in self.rpmRepos:
            rpmRepoCheck = self.checkInstalledXSAutoCertKitRepos(host,rpmRepo)
            if not rpmRepoCheck:
                reposFound = True
                break

        if (rpmInstalled == False and reposFound == False):
            xenrt.TEC().logverbose("XenServer Auto Cert Kit is already installed in the host.")
            return
        
        acklocation = xenrt.TEC().lookup("ACK_LOCATION", None)
        if not acklocation:
            if xenrt.TEC().lookup("TEST_CA-146164", False, boolean=True):
                if isinstance(host, xenrt.lib.xenserver.DundeeHost):
                    raise xenrt.XRTError("CA-146164 is not re-producible with Centos 7 dom0.")
                elif "x86_64" in host.execdom0("uname -a"):
                    branch = "creedence-autocertkit"
                    build = "88845"
                else:
                    branch = "clearwater-sp1-lcm-autocertkit"
                    build = "88844"

            elif xenrt.TEC().lookup("TEST_CA-160978", False, boolean=True):
                if isinstance(host, xenrt.lib.xenserver.DundeeHost):
                    branch = "trunk"
                    build = "91125"
                elif "x86_64" in host.execdom0("uname -a"):
                    branch = "creedence-autocertkit"
                    build = "91123"
                else:
                    raise xenrt.XRTError("Try with Creedence, Cream or Dundee to test CA-160978.")

            else:
                if isinstance(host, xenrt.lib.xenserver.DundeeHost):
                    branch = "trunk"
                elif "x86_64" in host.execdom0("uname -a"):
                    branch = "creedence-autocertkit"
                else:
                    branch = "clearwater-sp1-lcm-autocertkit"
                build = xenrt.util.getHTTP("https://xenbuilder.uk.xensource.com/search?query=latest&format=number&product=carbon&branch=%s&site=cam&job=sdk&action=xe-phase-2-build&status=succeeded" % (branch,)).strip()
            acklocation = "/usr/groups/xen/carbon/%s/%s/xe-phase-2/xs-auto-cert-kit.iso" % (branch, build)

        autoCertKitISO = xenrt.TEC().getFile(acklocation)
        try:
            xenrt.checkFileExists(autoCertKitISO)
        except:
            raise xenrt.XRTError("XenServer Auto Cert Kit ISO not found in xe-phase-2")

        hostPath = "/tmp/%s" % (self.pack)
        # Copy ISO from the controller to host in test
        sh = host.sftpClient()
        try:
            sh.copyTo(autoCertKitISO,hostPath)
        finally:
            sh.close()

        try:
            host.execdom0("xe-install-supplemental-pack /tmp/%s" % (self.pack))
        except:
            xenrt.TEC().logverbose("Unable to install XenServer Auto Cert Kit")

        for rpm in self.rpms:
            rpmInstalled = self.checkXSAutoCertKitRPMS(host,rpm)
            if not rpmInstalled:
                raise xenrt.XRTFailure("XenServer Auto Cert Kit RPM package %s is not installed" %
                                       (rpm))

        for rpmRepo in self.rpmRepos:
            rpmReposInstalled = self.checkInstalledXSAutoCertKitRepos(host,rpmRepo)
            if not rpmReposInstalled:
                raise xenrt.XRTFailure("XenServer Auto Cert Kit entries not found under installed-repos: %s" %
                                       (rpm))

    def checkInstalledXSAutoCertKitRepos(self, host, rpmRepo):
        # Check XenServer Auto Cert Kit entry exists under installed-repos
        try:
            data = host.execdom0("ls /etc/xensource/installed-repos/")
        except:
            return False
        if not rpmRepo in data:
            return False
        else:
            return True

    def checkXSAutoCertKitRPMS(self,host,rpm):
        # Check if the pack's rpms are installed
        try:
            data = host.execdom0("rpm -qi %s" % rpm)
        except:
            return False
        if "is not installed" in data:
            return False
        else:
            return True

    def ackResults(self):
        try:
            xmltext = self.pool.master.execdom0("cat /opt/xensource/packages/files/auto-cert-kit/test_run.conf", nolog=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTError("Error occured retrieving test_run.conf")
        else:
            results = {}
            dom = xml.dom.minidom.parseString(xmltext)
            devicecount = 0
            devices = dom.getElementsByTagName("device")
            for d in devices:
                classes = d.getElementsByTagName("test_class")
                for c in classes:
                    classname = c.getAttribute("name")
                    methods = c.getElementsByTagName("test_method")
                    for m in methods:
                        methodname = m.getAttribute("name")
                        result = xenrt.util.getTextFromXmlNode(m.getElementsByTagName("result")[0])
                        results["device%d/%s/%s" % (devicecount, classname, methodname)] = result
                devicecount += 1
            return results
    
    def waitForFinish(self):
        now = xenrt.util.timenow()
        testdeadline = now + 21600
        connectdeadline = now + 1800 + int(self.pool.master.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0"))
        time.sleep(180) # Extra time to allow the kit to get started
        while True:
            time.sleep(60)
            now = xenrt.util.timenow()
            if now > testdeadline:
                raise xenrt.XRTError("Auto cert kit timed out")
            try:
                connectdeadline = now + 1800 + int(self.pool.master.lookup("ALLOW_EXTRA_HOST_BOOT_SECONDS", "0"))
                fn = xenrt.TEC().tempFile()
                status = self.pool.master.execdom0("cd /opt/xensource/packages/files/auto-cert-kit && ./status.py", outfile=fn)
                if status == -1:
                    raise xenrt.XRTFailure("Command returned -1")
            except xenrt.XRTFailure, e:
                xenrt.TEC().logverbose("Couldn't SSH, %s" % str(e))
                now = xenrt.util.timenow()
                if now > connectdeadline:
                    raise xenrt.XRTError("Lost connection to host for longer than timeout during auto cert kit testing")
            else:
                f = open(fn)
                statustext = f.read().strip()
                xenrt.TEC().logverbose("Script returned error %d, text %s" % (status, statustext))
                f.close()
                if status == 1:
                    # Wait and check again in case the host was starting up/shutting down
                    time.sleep(60)
                    try:
                        status = self.pool.master.execdom0("cd /opt/xensource/packages/files/auto-cert-kit && ./status.py", retval="code")
                    except xenrt.XRTFailure, e:
                        xenrt.TEC().logverbose("Couldn't SSH, %s" % str(e))
                        continue
                    if status != 1:
                        continue
                    if self.EXPECTERROR:
                        self.error = True
                        xenrt.TEC().logverbose("Logged an expected error")
                        break
                    else:
                        raise xenrt.XRTError("Error occured in running auto cert kit")
                statuscode = int(statustext.split(":", 1)[0])
                if statuscode == 0:
                    break
                if statuscode == 1:
                    raise xenrt.XRTError("Error occured in running auto cert kit")
                if statuscode == 4:
                    raise xenrt.XRTError("Error occured in running auto cert kit")
            finally:
                os.unlink(fn)

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        # Download and perform XenServer Auto Cert Kit installation on all hosts in the pool
        for h in self.pool.getHosts():
            self.installXSAutoCertKit(h)

        # Proivde a switch for enabling XenRT to run the test kit on machines which only have
        # a single NIC. This flag disables non-compatible tests and ensure the management network
        # is used for all of the networking tests.
        if self.tec.lookup("SINGLE_NIC", False, boolean=True):
            self.SINGLE_NIC = "-o singlenic=true"

        # Machines in XenRT may have wrong hwclock time.
        # This may cause crashdump test case failed.
        # To avoid sync clock here.
        for host in self.getDefaultPool().getHosts():
            try:
                host.execdom0("hwclock --systohc")
            except:
                pass

    def createNetworkConfFile(self):
        nets = {self.pool.master.getDefaultInterface(): "NPRI"}
        nics = self.pool.master.listSecondaryNICs()
        
        netids = {"NPRI": 0, "NSEC": 1, "IPRI": 2, "ISEC": 3}

        for n in nics:
            netname = self.pool.master.getNICNetworkName(n)
            if netname in ["NPRI", "NSEC", "IPRI", "ISEC"]:
                nets[self.pool.master.getSecondaryNIC(n)] = netname
        
        xenrt.TEC().logverbose("Found primary NICs: %s" % nets)
        
        for s in self.pool.getSlaves():
            nics = s.listSecondaryNICs()
            slavenets = {s.getDefaultInterface(): "NPRI"}
            for n in nics:
                netname = s.getNICNetworkName(n)
                if netname in ["NPRI", "NSEC", "IPRI", "ISEC"]:
                    slavenets[s.getSecondaryNIC(n)] = netname
            xenrt.TEC().logverbose("Found slave NICs: %s from %s" % (slavenets, s.getName()))
            
            for n in nets.keys():
                if n not in slavenets.keys() or nets[n] != slavenets[n]:
                    xenrt.TEC().logverbose("Dropping net %s: %s" % (n, nets[n]))
                    del nets[n]
        
        # Delete if available NIC is less than 2 per network.
        if not self.tec.lookup("SINGLE_NIC", False, boolean=True):
            counter = {}
            for v in nets.values():
                if v in counter.keys():
                    counter[v] += 1
                else:
                    counter[v] = 1
            for n in nets.keys():
                if counter[nets[n]] < 2:
                    del nets[n]

        vids = []
        for v in ["VR01", "VR02", "VR03", "VR04", "VR05", "VR06", "VR07", "VR08"]:
            (vid, subnet, netmask) = self.pool.master.getVLAN(v)
            vids.append(str(vid))

        # Test for at least two NICs if not EXPECTERROR
        if (len(nets) < 2) and not self.EXPECTERROR and not xenrt.TEC().lookup("ALLOW_ACK_SINGLE_NIC", False, boolean=True):
            raise xenrt.XRTError("Less than two suitable NICs found")

        config = "#Interface,Network ID,VLANs\n"
        for n in sorted(nets.keys()):
            config += "%s = %d,[%s]\n" % (n, netids[nets[n]], ",".join(vids))

        self.pool.master.execdom0("echo \"%s\" > /opt/xensource/packages/files/auto-cert-kit/networkconf" % config.strip())
    
    def runACK(self):
        # Try to remove any ack-submission files
        try:
            self.pool.master.execdom0("rm /root/ack-submission*")
        except:
            pass
        self.pool.master.addExtraLogFile("/opt/xensource/packages/files/auto-cert-kit/ack_cli.log")
        self.pool.master.addExtraLogFile("/opt/xensource/packages/files/auto-cert-kit/test_run.conf")
        self.pool.master.addExtraLogFile("/var/log/auto-cert-kit.log")
        self.pool.master.addExtraLogFile("/var/log/auto-cert-kit-plugin.log")
        try:
            self.pool.master.execdom0("rm -f /opt/xensource/packages/files/auto-cert-kit/test_run.conf")

            optionstr = ""
            if self.tec.lookup("POF_ALL", False, boolean=True):
                optionstr += " -d"

            self.pool.master.execdom0("cd /opt/xensource/packages/files/auto-cert-kit; python ack_cli.py -n networkconf %s %s < /dev/null > ack_cli.log 2>&1 &" % (self.SINGLE_NIC, optionstr))
        except Exception, e:
            raise xenrt.XRTError("There is an error while running XenServer Auto Cert Kit %s" % str(e))
       
        self.waitForFinish()
        
        now = xenrt.util.timenow()
        deadline = now + 600
        while True:
            time.sleep(30)
            try:
                files = map(lambda x: x.strip(), self.pool.master.execdom0("ls /root/ack*").splitlines())
                break
            except:
                now = xenrt.util.timenow()
                if now > deadline:
                    raise xenrt.XRTError("No log file produced")
        for f in files:
            self.pool.master.addExtraLogFile(f)

    def processResults(self):
        results = self.ackResults()
        xenrt.TEC().logverbose("Cert kit complete, results:")
        for r in sorted(results.keys()):
            xenrt.TEC().logverbose("%s: %s" % (r, results[r]))
            fail = False
            optionalfail = False
            for f in self.FAILTCS:
                if re.match("^.*%s$" % f, r):
                    xenrt.TEC().logverbose("Expecting failure for %s" % r)
                    fail = True
            for f in self.OPTIONALFAILTCS:
                if re.match("^.*%s$" % f, r):
                    xenrt.TEC().logverbose("Expecting failure for %s" % r)
                    optionalfail = True
            if results[r] == "skip":
                result = xenrt.RESULT_SKIPPED
            elif results[r] == "pass":
                if fail:
                    result = xenrt.RESULT_FAIL
                else:
                    result = xenrt.RESULT_PASS
            else:
                if optionalfail or fail:
                    result = xenrt.RESULT_PASS
                else:
                    result = xenrt.RESULT_FAIL
            rr = r.split("/", 1)
            self.testcaseResult(rr[0], rr[1], result)
        
    def checkError(self):
        return True

    def run(self, arglist):
        self.createNetworkConfFile()
        try:
            self.runACK()
            if self.EXPECTERROR:
                raise xenrt.XRTFailure("Expected auto cert kit to error, but it didn't")
        except xenrt.XRTError, e:
            if self.EXPECTERROR and e.reason == "Error occured in running auto cert kit":
                if self.checkError():
                    xenrt.TEC().logverbose("Expected error occurred")
                else:
                    raise xenrt.XRTFailure("Expected error does not match actual error %s" % e.reason)
            else:
                raise
        finally:
            if not self.EXPECTERROR:
                self.processResults()
                
    def preLogs(self):
        host = self.getDefaultHost()
        for cd in host.listCrashDumps():
            try:
                host.destroyCrashDump(cd)
            except:
                pass


class XSAutoCertKit(_XSAutoCertKit):
    """Run the auto cert kit with good configuration"""

class XSAutoCertKitOneNIC(_XSAutoCertKit):
    """Run the auto cert kit with only one NIC (expect failure)"""
    EXPECTERROR = True

    def prepare(self, arglist):
        _XSAutoCertKit.prepare(self, arglist)
        # This TC expect to fail to launch with single nic config.
        self.SINGLE_NIC = ""

    def createNetworkConfFile(self):
        vids = []
        for v in ["VR01", "VR02", "VR03", "VR04", "VR05", "VR06", "VR07", "VR08"]:
            (vid, subnet, netmask) = self.pool.master.getVLAN(v)
            vids.append(str(vid))

        config = "#Interface,Network ID,VLANs\n"
        config += "%s = 0,[%s]\n" % (self.pool.master.getDefaultInterface(), ",".join(vids))

        self.pool.master.execdom0("echo \"%s\" > /opt/xensource/packages/files/auto-cert-kit/networkconf" % config.strip())

    def checkError(self):
        errorString = "at least 2 network interfaces"
        log = self.pool.master.execdom0("cat /opt/xensource/packages/files/auto-cert-kit/ack_cli.log", nolog=True)
        if errorString in log:
            return True
        return False
        
class XSAutoCertKitSingleHost(_XSAutoCertKit):
    """Run the auto cert kit with only one host (expect failure)"""
    EXPECTERROR = True
    
    def checkError(self):
        errorString = "at least two hosts"
        log = self.pool.master.execdom0("cat /opt/xensource/packages/files/auto-cert-kit/ack_cli.log", nolog=True)
        if errorString in log:
            return True
        return False

class XSAutoCertKitNoStorage(_XSAutoCertKit):
    """Run the auto cert kit with only no shared storage. Expect to use local storage instead."""

class XSAutoCertKitWrongVLAN(_XSAutoCertKit):
    """Run the auto cert kit with the wrong VLAN IDs (expect failure)"""
    INVALID_VIDS="2,3"

    FAILTCS = ["\/network_tests\.VLANTestClass.*"]
    def createNetworkConfFile(self):
        nets = {self.pool.master.getDefaultInterface(): "NPRI"}
        nics = self.pool.master.listSecondaryNICs()

        netids = {"NPRI": 0, "NSEC": 1, "IPRI": 2, "ISEC": 3}

        for n in nics:
            netname = self.pool.master.getNICNetworkName(n)
            if netname in ["NPRI", "NSEC", "IPRI", "ISEC"]:
                nets[self.pool.master.getSecondaryNIC(n)] = netname

        for s in self.pool.getSlaves():
            nics = s.listSecondaryNICs()
            slavenets = {s.getDefaultInterface(): "NPRI"}
            for n in nics:
                netname = s.getNICNetworkName(n)
                if netname in ["NPRI", "NSEC", "IPRI", "ISEC"]:
                    slavenets[s.getSecondaryNIC(n)] = netname
            for n in nets.keys():
                if n not in slavenets.keys() or nets[n] != slavenets[n]:
                    del nets[n]
        
        # Delete if available NIC is less than 2 per network.
        if not self.tec.lookup("SINGLE_NIC", False, boolean=True):
            counter = {}
            for v in nets.values():
                if v in counter.keys():
                    counter[v] += 1
                else:
                    counter[v] = 1
            for n in nets.keys():
                if counter[nets[n]] < 2:
                    del nets[n]

        config = "#Interface,Network ID,VLANs\n"
        for n in sorted(nets.keys()):
            config += "%s = %d,[%s]\n" % (n, netids[nets[n]],self.INVALID_VIDS)

        self.pool.master.execdom0("echo \"%s\" > /opt/xensource/packages/files/auto-cert-kit/networkconf" % config.strip())

class XSAutoCertKitInvalidBond(_XSAutoCertKit):
    """Run the auto cert kit with an invalid bond config (expect failure)"""
    FAILTCS = ["\/network_tests\.BondingTestClass.*"]
    OPTIONALFAILTCS = ["\/network_tests.*"]
    def createNetworkConfFile(self):
        nics = self.pool.master.listSecondaryNICs()
        usenics = []

        netids = {"NPRI": 0, "NSEC": 1, "IPRI": 2, "ISEC": 3}

        npri = False
        nsec = False

        for n in nics:
            netname = self.pool.master.getNICNetworkName(n)
            if not npri and netname == "NPRI":
                npri = True
                usenics.append(self.pool.master.getSecondaryNIC(n))
            if not nsec and netname == "NSEC":
                nsec = True
                usenics.append(self.pool.master.getSecondaryNIC(n))

        vids = []
        for v in ["VR01", "VR02", "VR03", "VR04", "VR05", "VR06", "VR07", "VR08"]:
            (vid, subnet, netmask) = self.pool.master.getVLAN(v)
            vids.append(str(vid))
        
        config = "#Interface,Network ID,VLANs\n"
        for n in usenics:
            config += "%s = 0,[%s]\n" % (n, ",".join(vids))

        self.pool.master.execdom0("echo \"%s\" > /opt/xensource/packages/files/auto-cert-kit/networkconf" % config.strip())
    
    
