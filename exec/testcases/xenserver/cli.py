#
# XenRT: Test harness for Xen and the XenServer product family
#
# CLI functional tests
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, shutil, os.path, stat, re, os, time, urllib, glob
import traceback
import xenrt, xenrt.lib.xenserver

class TCCLI(xenrt.TestCase):
    """Tests the Rio+ CLI"""

    def __init__(self, tcid="TCCLI"):
        xenrt.TestCase.__init__(self, tcid)
        self.hostToClean = None
        self.vdi = None
        self.vbd = None
        self.tmpdev = None
        self.vg = None
        self.reboot = True

    def run(self, arglist=None):
        selected_tests = None
        machine = "RESOURCE_HOST_0"
        guests = "debian-pv,windowsxp"
        uselocalsr = False
        #guests = "linuxhvm,debian-pv,windowsxp"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        if arglist and len(arglist) > 1:
            for arg in arglist[1:]:
                l = string.split(arg, "=", 1)
                if l[0] == "tests":
                    selected_tests = l[1]
                    if selected_tests == "ALL":
                        selected_tests = None
                if l[0] == "guests":
                    guests = l[1]
                if l[0] == "noreboot":
                    self.reboot = False
                if l[0] == "localsr":
                    uselocalsr = True
        guests = string.split(guests, ",")

        host = xenrt.TEC().registry.hostGet(machine)
        self.hostToClean = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        sftp = host.sftpClient()
        cli = host.getCLIInstance()

        # Get the test binaries
        testtar = xenrt.TEC().lookup("CLI_REGRESSION_TESTS", None)
        if not testtar:
            # Try the same directory as the ISO
            testtar = xenrt.TEC().getFile("cli-regress.tar.gz",
                                          "xe-phase-1/cli-regress.tar.gz")
        if not testtar:
            raise xenrt.XRTError("No CLI regression test tarball given")
        d = self.tec.tempDir()
        xenrt.command("tar -zxf %s -C %s" % (testtar, d))
        if not os.path.exists("%s/test_host" % (d)):
            raise xenrt.XRTError("test_host not found in test tarball")
        host.execdom0("mkdir -p /tmp/rt", level=xenrt.RC_ERROR)
        sftp.copyTreeTo(d, "/tmp/rt")
        if host.execdom0("test -e /opt/xensource/bin/gtclient",
                         retval="code") != 0:
            host.execdom0("cp -p /tmp/rt/gtclient /opt/xensource/bin/")

        # Binaries that aren't in the per-build output
        xenrt.getTestTarball("api", extract=True, copy=False)
        fn = xenrt.TEC().tempFile()
        sftp.copyTo("%s/api/dom0/test.css" % (xenrt.TEC().getWorkdir()),
                    "/tmp/rt/test.css")
        sftp.copyTo("%s/api/dom0/test_log.js" % (xenrt.TEC().getWorkdir()),
                    "/tmp/rt/test_log.js")

        # Newer builds have the guest agent source in the build tarball
        if os.path.exists("%s/gtserver" % (d)):
            linuxagentsrc = "%s/gtserver/*" % (d)
            linuxagentmake = True
        else:
            linuxagentsrc = "%s/api/linux/*.ml" % (xenrt.TEC().getWorkdir())
            linuxagentmake = False

        # Required packages in dom0
        for p in ['nc', 'rsync']:
            try:
                host.execdom0("yum -y install %s" % (p))
            except:
                pass

        # Make a VDI for import/export tests, mount it on /mnt
        if host.execdom0("test -e /etc/xensource/.importexportcookie", retval="code") != 0:
            try:
                dom0 = host.getMyDomain0UUID()
                srl = host.getSRs(type="ext")
                lvm = False
                if len(srl) == 0:
                    srl = host.getSRs("lvm")
                    if len(srl) > 0:
                        lvm = True
                if len(srl) == 0:
                    raise xenrt.XRTError("Could not find suitable SR for temp "
                                         "storage")
                sr = srl[0]
                if lvm:
                    # Provision with LVM tools
                    vgs = host.execRawStorageCommand(sr, "vgs --noheadings -o size,name,size "
                                        "--separator=, | cut -d, -f2").split()
                    self.vg = None
                    for vg in vgs:
                        if re.search(r"XenSwap", vg):
                            continue
                        if re.search(r"XenConfig", vg):
                            continue
                        if re.search(r"read failed", vg):
                            continue
                        try:
                            host.execRawStorageCommand(sr, "lvcreate -n importexport -L 10G %s" % (vg))
                            self.vg = vg
                            break
                        except:
                            pass
                    if not self.vg:
                        raise xenrt.XRTError("No suitable VG found for "
                                             "importexport volume")
                    dev = "%s/importexport" % (self.vg)
                else:
                    # Provision via official channels
                    vdi = string.strip(cli.execute("vdi-create",
                                                   "name-label=importexport "
                                                   "type=user sr-uuid=%s "
                                                   "virtual-size=10000000000" %
                                                   (sr),
                                                   compat=False))
                    self.vdi = vdi
                    vbd = string.strip(cli.execute("vbd-create",
                                                   "vdi-uuid=%s vm-uuid=%s "
                                                   "device=autodetect" %
                                                   (vdi, dom0),
                                                   compat=False))
                    self.vbd = vbd
                    cli.execute("vbd-plug", "uuid=%s" % (vbd), compat=False)
                    dev = string.strip(cli.execute("vbd-param-get",
                                                   "uuid=%s param-name=device" %
                                                   (vbd),
                                                   compat=False))

                host.execdom0("mke2fs /dev/%s" % (dev), level=xenrt.RC_ERROR)
                host.execdom0("mount /dev/%s /mnt" % (dev),
                              level=xenrt.RC_ERROR)
                self.tmpdev = dev
                host.execdom0("touch /etc/xensource/.importexportcookie")
            except xenrt.XRTFailure, e:
                # Anything that breaks here is not a failure of the CLI RT
                raise xenrt.XRTError(e.reason)

        vms = []
        try:
            if uselocalsr:
                sruuid = host.getLocalSR()
                if host.pool:
                    host.pool.setPoolParam("default-SR", sruuid)
            else:
                sruuid = None
            # Install some guests
            if "linuxhvm" in guests:
                try:
                    t = host.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP_SP3")
                except:
                    t = host.chooseTemplate("TEMPLATE_NAME_WINDOWS_XP")
                linuxhvm = host.guestFactory()(\
                    "linuxhvm", t)
                linuxhvm.windows = False
                linuxhvm.setMemory(256)
                method = "HTTP"
                repository = string.split(\
                    xenrt.TEC().lookup(["RPM_SOURCE", "rhel5", "x86-32",
                                        method]))[0]
                linuxhvm.install(host,
                                 distro="rhel5",
                                 repository=repository,
                                 method=method,
                                 pxe=True,
                                 extrapackages=["dosfstools"],
                                 sr=sruuid)
                linuxhvm.check()
                xenrt.TEC().registry.guestPut("linuxhvm", linuxhvm)

                ltmp = string.strip(linuxhvm.execguest("mktemp -d /tmp/XXXXXX"))
                lsftp = linuxhvm.sftpClient()
                lsftp.copyTo("%s/api/rhel5/ocaml-3.09.1-1.2.el5.rf.i386.rpm" %
                             (xenrt.TEC().getWorkdir()),
                             "%s/ocaml-3.09.1-1.2.el5.rf.i386.rpm" % (ltmp))
                linuxhvm.execguest("rpm --install "
                                   "%s/ocaml-3.09.1-1.2.el5.rf.i386.rpm"
                                   % (ltmp))
                for f in glob.glob(linuxagentsrc):
                    lsftp.copyTo(f, "%s/%s" % (ltmp, os.path.basename(f)))
                if linuxagentmake:
                    linuxhvm.execguest("make -C %s" % (ltmp))
                    linuxhvm.execguest("cp %s/gtserver /root/gtserver" %
                                       (ltmp))
                else:
                    linuxhvm.execguest("cd %s; "
                                       "ocamlc -o /root/gtserver unix.cma"
                                       " gtmessages.ml gtcomms.ml "
                                       " gtlinuxops.ml "
                                       " gtserver_linux.ml" % (ltmp))
                linuxhvm.execguest("chmod 755 /root/gtserver")
                linuxhvm.execguest("echo 'exec /root/gtserver &' >> "
                                   "/etc/rc.local")
                linuxhvm.execguest("/sbin/chkconfig iptables off || true")

                vms.append(linuxhvm)

            if "debian-pv" in guests:
                debianpv = host.createGenericLinuxGuest(name="debian-pv",
                                                        vcpus=1,
                                                        sr=sruuid)
                debianpv.setMemory(256)
                debianpv.check()
                xenrt.TEC().registry.guestPut("debian-pv", debianpv)

                debianpv.execguest("apt-get -y --force-yes install ocaml")
                dtmp = string.strip(debianpv.execguest("mktemp -d /tmp/XXXXXX"))
                dsftp = debianpv.sftpClient()
                for f in glob.glob(linuxagentsrc):
                    dsftp.copyTo(f, "%s/%s" % (dtmp, os.path.basename(f)))
                if linuxagentmake:
                    debianpv.execguest("make -C %s" % (dtmp))
                    debianpv.execguest("cp %s/gtserver /root/gtserver" %
                                       (dtmp))
                else:
                    debianpv.execguest("cd %s; "
                                       "ocamlc -o /root/gtserver unix.cma"
                                       " gtmessages.ml gtcomms.ml "
                                       " gtlinuxops.ml "
                                       " gtserver_linux.ml" % (dtmp))
                debianpv.execguest("chmod 755 /root/gtserver")
                debianpv.execguest("echo 'exec /root/gtserver &' >> "
                                   "/etc/init.d/apirt")
                debianpv.execguest("chmod +x /etc/init.d/apirt")
                debianpv.execguest("update-rc.d apirt start 99 2 .")
                debianpv.execguest("apt-get install --force-yes -y dosfstools")
                debianpv.execguest(\
                    "rm -f /etc/udev/rules.d/z25_persistent-net.rules "
                    "/etc/udev/persistent-net-generator.rules")
                                   
                vms.append(debianpv)

            if "windowsxp" in guests:
                distro = "winxpsp3"
                template = host.getTemplate(distro)
                windowsxp = host.guestFactory()("windowsxp", template)
                windowsxp.setMemory(256)
                windowsxp.install(host,
                                  isoname=xenrt.DEFAULT,
                                  distro=distro,
                                  sr=sruuid)
                xenrt.TEC().registry.guestPut("windowsxp", windowsxp)
                windowsxp.installDrivers()
                
                try:
                    windowsxp.xmlrpcExec("del /F /S /Q c:\\xen")
                    windowsxp.xmlrpcExec("rmdir c:\\xen")
                except:
                    pass
                windowsxp.xmlrpcExec("mkdir c:\\xen")
                for f in glob.glob("%s/api/windows/*" %
                                   (xenrt.TEC().getWorkdir())):
                    windowsxp.xmlrpcSendFile(f, "c:\\xen\\%s" %
                                             (os.path.basename(f)))
                fn = xenrt.TEC().tempFile()
                f = file(fn, "w")
                f.write("cd c:\\xen\n")
                f.write("c:\\xen\\gtserver_win.exe\n")
                f.close()
                windowsxp.xmlrpcSendFile(fn, "c:\\xen\\starttest.cmd")
                windowsxp.xmlrpcExec("c:\\windows\\system32\\netsh.exe "
                                     "firewall set opmode DISABLE")
                windowsxp.winRegAdd("HKLM",
                                    "SOFTWARE\\Microsoft\\Windows\\"
                                    "CurrentVersion\\Run",
                                    "APIRTDaemon",
                                    "SZ",
                                    "c:\\xen\\starttest.cmd")

                vms.append(windowsxp)

            # Shut down the guests
            for vm in vms:
                vm.shutdown()

        except xenrt.XRTFailure, e:
            # Anything that breaks here is not a failure of the CLI RT
            raise xenrt.XRTError(e.reason)

        # Run the tests
        if not selected_tests:
            targ = "-a"
        else:
            targ = "-t %s" % (selected_tests)
        intf = string.replace(host.getPrimaryBridge(), "xenbr", "eth")
        pathstr = "${PATH}:."
        commands = ["cd /tmp/rt",
                    "export PATH=%s" % (pathstr),
                    "test_host %s -v %s -i %s" %
                    (targ, string.join(guests, ","), intf)]
        self.runAsync(host, commands, timeout=14400)

        # Copy the logs back
        try:
            sftp.copyTreeFrom("/tmp/rt", "%s/results" %
                              (xenrt.TEC().getLogdir()))
        except Exception, e:
            # Try again
            xenrt.TEC().warning("Exception copying logs on first go (%s)" %
                                str(e))
            traceback.print_exc(file=sys.stderr)
            shutil.rmtree("%s/results" % (xenrt.TEC().getLogdir()))
            sftp.copyTreeFrom("/tmp/rt", "%s/results" %
                              (xenrt.TEC().getLogdir()))            
        xenrt.TEC().logverbose("Closing SFTP connection to dom0")
        sftp.close()

        # Parse the XML results file
        xmlfile = "%s/results/test_log.xml" % (xenrt.TEC().getLogdir())
        if not os.path.exists(xmlfile):
            raise xenrt.XRTFailure("No results file was returned (%s)" %
                                   (xmlfile))
        xenrt.TEC().logverbose("About to parse results file")
        self.readResults(xmlfile)

        # Check the health of the dom0
        xenrt.TEC().logverbose("Checking dom0 health")
        host.checkHealth()
        xenrt.TEC().logverbose("Done")

    def postRun(self):
        if self.hostToClean:
            toraise = None
            cli = self.hostToClean.getCLIInstance()
            
            try:
                self.hostToClean.execdom0("rm -rf /tmp/rt")
            except:
                pass
            
            # Clean up the temp space
            try:
                if self.tmpdev:
                    self.hostToClean.execdom0("umount /mnt")
                    self.hostToClean.execdom0("rm -f /etc/xensource/.importexportcookie")

            except Exception, e:
                toraise = e
            # Find SR uuid before delete vdi and vg.
            sr = None
            if self.vdi and self.vg:
                sr = self.hostToClean.genParamGet("vdi", self.vdi, "sr-uuid")
            try:
                if self.vbd:
                    cli.execute("vbd-unplug",
                                "uuid=%s" % (self.vbd),
                                compat=False)
            except Exception, e:
                toraise = e
            try:
                if self.vbd:
                    cli.execute("vbd-destroy",
                                "uuid=%s" % (self.vbd),
                                compat=False)
            except Exception, e:
                toraise = e
            try:
                if self.vdi:
                    cli.execute("vdi-destroy",
                                "uuid=%s" % (self.vdi),
                                compat=False)
            except Exception, e:
                toraise = e
            
            # Clean up mounts and LVs
            try:
                if self.vg:
                    self.hostToClean.execRawStorageCommand(sr, "lvremove --force "
                                              "/dev/%s/importexport" %
                                              (self.vg))
            except Exception, e:
                toraise = e

            # Kill any left over domains
            try:
                self.hostToClean.uninstallAllGuests()
            except Exception, e:
                toraise = e

            # Put back the correct license
            try:
                if xenrt.TEC().lookup("OPTION_APPLY_LICENSE",
                                      True,
                                      boolean=True):
                    self.hostToClean.license()
            except Exception, e:
                toraise = e

            try:
                if self.reboot:
                    self.hostToClean.reboot()
            except Exception, e:
                toraise = e

            if toraise != None:
                raise toraise

class TCRioQoSBasic(xenrt.TestCase):

    def __init__(self, tcid="TCRioQoSBasic"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0" 
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        self.hostToClean = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                (machine))
        self.getLogsFrom(host)
        g = host.createGenericLinuxGuest(start=False)
        self.guestsToClean.append(g)

        self.declareTestcase("sched-credit-weight", "set_and_check")
        self.declareTestcase("sched-credit-weight", "reset")
        self.declareTestcase("sched-credit-cap", "set_and_check")
        self.declareTestcase("sched-credit-cap", "reset")

        xenrt.TEC().progress("Setting and checking credit weight parameter.")
        reason = None
        for p in [ 128, 256, 512 ]:
            xenrt.TEC().logverbose("Attempting to set weight to %s." % (p))
            try:
                g.setCPUCredit(weight=p, cap=0)
            except Exception, e:
                reason = "Failed to set credit parameters. (%s)" % (e)
            try:
                w, c = g.getCPUCredit()
                if not w == p:
                    reason = "Weight is %s not %s." % (w, p)
                if not c == 0:
                    reason = "Cap is %s not 0." % (c)
            except Exception, e:
                reason = "Failed to get credit parameters. (%s)" % (e)
            if not reason:
                try:
                    g.start()
                except Exception, e:
                    reason = "Error starting guest. (%s)" % (e)
            if not reason:
                try:
                    domid = g.getDomid()
                    data = host.execdom0("/opt/xensource/debug/xenops sched_get -domid %s" % (domid)).strip()
                    w, c = data.split(" ")
                    if not w == str(p):
                        reason = "Weight is %s not %s." % (w, p)
                    if not c == '0':
                        reason = "Cap is %s not 0." % (c)
                except Exception, e:
                    reason = "Error checking credit parameters. (%s)" % (e)
            try:
                g.shutdown()
            except:
                pass
            if reason:
                break

        if reason:
            self.testcaseResult("sched-credit-weight", "set_and_check",
                                 xenrt.RESULT_FAIL, reason)
        else:
            self.testcaseResult("sched-credit-weight", "set_and_check",
                                 xenrt.RESULT_PASS)

        reason = None
        try:
            # Reset state.
            g.setCPUCredit() 
        except Exception, e:
            reason = "Failed to reset credit parameters. (%s)" % (e)
        if not reason:
            try:
                w, c = g.getCPUCredit()
                if w or c:
                    reason = "Weight and Cap have not been reset."
            except Exception, e:
                reason = "Failed to get credit parameters. (%s)" % (e)

        if reason:
            self.testcaseResult("sched-credit-weight", "reset",
                                 xenrt.RESULT_FAIL, reason)
        else:
            self.testcaseResult("sched-credit-weight", "reset",
                                 xenrt.RESULT_PASS)
       
        xenrt.TEC().progress("Setting and checking credit cap parameter.")
        reason = None
        for p in [ 10, 50, 75 ]:
            try:
                g.setCPUCredit(weight=256, cap=p)
            except Exception, e:
                reason = "Failed to set credit parameters."
            try:
                w, c = g.getCPUCredit()
                if not w == 256:
                    reason = "Weight is %s not 256." % (w)
                if not c == p:
                    reason = "Cap is %s not %s." % (c, p)
            except:
                reason = "Failed to get credit parameters."
            if not reason:
                try:
                    g.start()
                except:
                    reason = "Error starting guest."
            if not reason:
                try:
                    domid = g.getDomid()
                    data = host.execdom0("/opt/xensource/debug/xenops sched_get -domid %s" % (domid)).strip()
                    w, c = data.split(" ")
                    if not w == '256': 
                        reason = "Weight is %s not 256." % (w)
                    if not c == str(p):
                        reason = "Cap is %s not %s." % (c, p)
                except:
                    reason = "Error checking credit parameters."
            try:
                g.shutdown()
            except:
                pass
            if reason:
                break

        if reason:
            self.testcaseResult("sched-credit-cap", "set_and_check",
                                 xenrt.RESULT_FAIL, reason)
        else:
            self.testcaseResult("sched-credit-cap", "set_and_check",
                                 xenrt.RESULT_PASS)
    
        reason = None
        try:
            g.setCPUCredit()
        except:
            reason = "Failed to reset credit parameters."
        if not reason:
            try:
                w, c = g.getCPUCredit()
                if w or c:
                    reason = "Weight and Cap have not been reset."
            except:
                reason = "Failed to get credit parameters."
            
        if reason:
            self.testcaseResult("sched-credit-cap", "reset",
                                 xenrt.RESULT_FAIL, reason)
        else:
            self.testcaseResult("sched-credit-cap", "reset",
                                 xenrt.RESULT_PASS) 

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)

def parseSchedCredit(s):
    """Parse the output of xm sched-credit to return (cap, weight)"""
    r = re.search(r"\{'cap': (\d+), 'weight': (\d+)\}", s)
    if not r:
        raise xenrt.XRTError("Unable to parse sched-credit output")
    return (int(r.group(1)), int(r.group(2)))
        
class TCQoSBasic(xenrt.TestCase):

    def __init__(self, tcid="TCQoSBasic"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        self.hostToClean = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        self.declareTestcase("sched-credit-weight", "check_default")
        self.declareTestcase("sched-credit-weight", "param_exists")
        self.declareTestcase("sched-credit-weight", "set_and_check")
        self.declareTestcase("sched-credit-weight", "set_to_null")
        self.declareTestcase("sched-credit-cap", "check_default")
        self.declareTestcase("sched-credit-cap", "param_exists")
        self.declareTestcase("sched-credit-cap", "set_and_check")
        self.declareTestcase("sched-credit-cap", "set_to_null")

        #####################################################################
        # Weight settings

        b = False
        
        # Create a guest
        g = host.createGenericLinuxGuest(start=False)
        self.guestsToClean.append(g)

        cli = host.getCLIInstance()

        # Check for the param
        data = cli.execute("vm-param-list", "vm-name=%s" % (g.name))
        if re.search(r"sched_credit_weight:", data):
            self.testcaseResult("sched-credit-weight", "param_exists",
                                xenrt.RESULT_PASS)
        else:
            self.testcaseResult("sched-credit-weight", "param_exists",
                                xenrt.RESULT_FAIL,
                                "No sched_credit_weight found")
            b = False

        # Make sure the default is correct
        reason = None
        try:
            x = g.paramGet("sched_credit_weight")
            if x != "(null)":
                reason = "sched_credit_weight %s is not '(null)'" % (x)
        except:
            reason = "Error getting sched_credit_weight param"
        if reason:
            self.testcaseResult("sched-credit-weight", "check_default",
                                xenrt.RESULT_FAIL, reason)
        else:
            self.testcaseResult("sched-credit-weight", "check_default",
                                xenrt.RESULT_PASS)

        # Try setting some params
        if not b:
            reason = None
            for p in [128, 256, 512]:
                started = False
                try:
                    g.paramSet("sched_credit_weight", "%u" % (p))
                except:
                    reason = "Error setting sched_credit_weight param"
                try:
                    x = g.paramGet("sched_credit_weight")
                    if int(x) != p:
                        reason = "sched_credit_weight %s is not %u" % (x, p)
                except:
                    reason = "Error getting sched_credit_weight param"
                if not reason:
                    try:
                        g.start()
                        started = True
                    except:
                        reason = "Error starting guest"
                if not reason:
                    try:
                        # Check this has been set
                        domid = g.getDomid()
                        data = g.host.execdom0("xm sched-credit -d %u" %
                                               (domid))
                        cap, weight = parseSchedCredit(data)
                        if weight != p:
                            reason = "weight %u is not what we set (%u)" % \
                                     (weight, p)
                    except:
                        reason = "Error checking sched_credit_weight"
                if started:
                    g.shutdown()
                if reason:
                    break
            if reason:
                self.testcaseResult("sched-credit-weight", "set_and_check",
                                    xenrt.RESULT_FAIL, reason)
                b = True
            else:
                self.testcaseResult("sched-credit-weight", "set_and_check",
                                    xenrt.RESULT_PASS)
                
        # Make sure we can set back to null
        if not b:
            reason = None
            try:
                g.paramSet("sched_credit_weight", "null")
            except:
                reason = "Error setting sched_credit_weight param"
            if not reason:
                try:
                    x = g.paramGet("sched_credit_weight")
                    if x != "(null)":
                        reason = "sched_credit_weight %s is not '(null)'" % (x)
                except:
                    reason = "Error getting sched_credit_weight param"
            if reason:
                self.testcaseResult("sched-credit-weight", "set_to_null",
                                    xenrt.RESULT_FAIL, reason)
                b = True
            else:
                self.testcaseResult("sched-credit-weight", "set_to_null",
                                    xenrt.RESULT_PASS)

        #####################################################################
        # Cap settings

        b = False

        # Check for the param
        data = cli.execute("vm-param-list", "vm-name=%s" % (g.name))
        if re.search(r"sched_credit_cap:", data):
            self.testcaseResult("sched-credit-cap", "param_exists",
                                xenrt.RESULT_PASS)
        else:
            self.testcaseResult("sched-credit-cap", "param_exists",
                                xenrt.RESULT_FAIL,
                                "No sched_credit_cap found")
            b = False

        # Make sure the default is correct
        reason = None
        try:
            x = g.paramGet("sched_credit_cap")
            if x != "(null)":
                reason = "sched_credit_cap %s is not '(null)'" % (x)
        except:
            reason = "Error getting sched_credit_cap param"
        if reason:
            self.testcaseResult("sched-credit-cap", "check_default",
                                xenrt.RESULT_FAIL, reason)
        else:
            self.testcaseResult("sched-credit-cap", "check_default",
                                xenrt.RESULT_PASS)

        # Try setting some params
        if not b:
            reason = None
            for p in [10, 50, 75]:
                started = False
                try:
                    g.paramSet("sched_credit_cap", "%u" % (p))
                except:
                    reason = "Error setting sched_credit_cap param"
                try:
                    x = g.paramGet("sched_credit_cap")
                    if int(x) != p:
                        reason = "sched_credit_cap %s is not %u" % (x, p)
                except:
                    reason = "Error getting sched_credit_cap param"
                if not reason:
                    try:
                        g.start()
                        started = True
                    except:
                        reason = "Error starting guest"
                if not reason:
                    try:
                        # Check this has been set
                        domid = g.getDomid()
                        data = g.host.execdom0("xm sched-credit -d %u" %
                                               (domid))
                        cap, weight = parseSchedCredit(data)
                        if cap != p:
                            reason = "cap %u is not what we set (%u)" % \
                                     (cap, p)
                    except:
                        reason = "Error checking sched_credit_cap"
                if started:
                    g.shutdown()
                if reason:
                    break
            if reason:
                self.testcaseResult("sched-credit-cap", "set_and_check",
                                    xenrt.RESULT_FAIL, reason)
                b = True
            else:
                self.testcaseResult("sched-credit-cap", "set_and_check",
                                    xenrt.RESULT_PASS)
                
        # Make sure we can set back to null
        if not b:
            reason = None
            try:
                g.paramSet("sched_credit_cap", "null")
            except:
                reason = "Error setting sched_credit_cap param"
            if not reason:
                try:
                    x = g.paramGet("sched_credit_cap")
                    if x != "(null)":
                        reason = "sched_credit_cap %s is not '(null)'" % (x)
                except:
                    reason = "Error getting sched_credit_cap param"
            if reason:
                self.testcaseResult("sched-credit-cap", "set_to_null",
                                    xenrt.RESULT_FAIL, reason)
                b = True
            else:
                self.testcaseResult("sched-credit-cap", "set_to_null",
                                    xenrt.RESULT_PASS)

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)

class TCRioCPUControl(xenrt.TestCase):

    def __init__(self, tcid="TCRioCPUControl"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []

    
    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        self.hostToClean = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        g = host.createGenericLinuxGuest(start=False)
        self.guestsToClean.append(g)
        g.cpuset(2)

        # Pin vcpus to some physical ones and check.
        cores = host.getCPUCores()
        mask = []
        for i in range(0, cores):
            mask = mask + [i]
            g.paramSet("VCPUs-params-mask", "%s" % (re.sub("[ \[\]]", "", str(mask))))
            g.start()
            domid = g.getDomid()
            for c in range(0, g.vcpus):
                data = host.execdom0("/opt/xensource/debug/xenops affinity_get -domid %s -vcpu %s" % 
                                    (domid, c)).strip()
                for j in mask:
                    if not int(list(data)[j]) == 1:
                        raise xenrt.XRTFailure("VCPU %s is not pinned to CPU %s." % (c, j))
            g.shutdown()
        g.paramRemove("VCPUs-params", "mask")

        # Add and remove some VCPUs and check, both in guest and dom0.
        g.start()
        if not g.getMyVCPUs() == 2:
            raise xenrt.XRTFailure("Guest doesn't agree on VCPUs.")
        if not g.paramGet("VCPUs-number"):
            raise xenrt.XRTFailure("Dom-0 doesn't agree on VCPUs.")
        g.cpuset(1, live=True)
        time.sleep(30)
        if not g.getMyVCPUs() == 1:
            raise xenrt.XRTFailure("Guest doesn't agree on VCPUs.")
        if not g.paramGet("VCPUs-number"):
            raise xenrt.XRTFailure("Dom-0 doesn't agree on VCPUs.")
        g.cpuset(2, live=True)
        time.sleep(30)
        if not g.getMyVCPUs() == 2:
            raise xenrt.XRTFailure("Guest doesn't agree on VCPUs.")
        if not g.paramGet("VCPUs-number"):
            raise xenrt.XRTFailure("Dom-0 doesn't agree on VCPUs.")

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)

class TCCPUControl(xenrt.TestCase):

    def __init__(self, tcid="TCCPUControl"):
        xenrt.TestCase.__init__(self, tcid)
        self.guestsToClean = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        self.hostToClean = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        self.declareTestcase("VCPU_change", "VCPU_change")
        self.declareTestcase("pinning", "param_exists")

        b = False
        
        # Create a guest
        g = host.createGenericLinuxGuest(start=False)
        self.guestsToClean.append(g)
        g.cpuset(2)

        cli = host.getCLIInstance()

        #####################################################################
        # Pinning

        # Check for the param
        data = cli.execute("vm-param-list", "vm-name=%s" % (g.name))
        if re.search(r"vcpu_pin:", data):
            self.testcaseResult("pinning", "param_exists",
                                xenrt.RESULT_PASS)
        else:
            self.testcaseResult("pinning", "param_exists",
                                xenrt.RESULT_FAIL,
                                "No vcpu_pin param found")
            b = False

        # Try some affinity settings
        for a in [("all_on_0", ["0"])]:
            reason = None
            started = False
            desc, l = a
            v = string.join(l, ",")
            try:
                g.paramSet("vcpu_pin", v)
            except:
                reason = "Error setting vcpu_pin parameter"
            if not reason:
                try:
                    x = string.strip(g.paramGet("vcpu_pin"))
                    if x != v:
                        reason = "Set vcpu_pin %s is not what we asked for " \
                                 "(%s)" % (x, v)
                except:
                    reason = "Error getting parameter vcpu_pin"
            if not reason:
                try:
                    g.start()
                    started = True
                except:
                    reason = "Error starting guest"
            if not reason:
                domid = g.getDomid()
                cpus = string.split(\
                    g.host.execdom0("xm vcpu-list %u | grep -v \"^Name\" | "
                                    "awk '{print $4}'" % (domid)))
                if len(cpus) != 2:
                    reason = "Guest did not have 2 VCPUs (%u)" % (len(cpus))
                if not reason:
                    for i in range(len(cpus)):
                        if not cpus[i] in l:
                            reason = "VCPU %u is not on an allowed CPU (%u)" \
                                     % (i, cpus[i])
                            
            if started:
                g.shutdown()

            if reason:
                self.testcaseResult("pinning", "set_%s" % (desc),
                                    xenrt.RESULT_FAIL, reason)
            else:
                self.testcaseResult("pinning", "set_%s" % (desc),
                                    xenrt.RESULT_PASS)


        #####################################################################
        # CPU hotplug
        g.paramSet("vcpu_pin", "null")
        g.start()
                   
        # Check we're running with 2 VCPUs
        reason = None
        domid = g.getDomid()
        cpus = string.split(\
            g.host.execdom0("xm vcpu-list %u | grep -v \"^Name\" | "
                            "awk '{print $4}'" % (domid)))
        if len(cpus) != 2:
            reason = "Guest did not have 2 VCPUs (%u)" % (len(cpus))
        if not reason:
            for i in range(len(cpus)):
                if not re.search(r"\d+", cpus[i]):
                    reason = "VCPU %u not assigned to physical CPU ('%s')." % \
                             (cpus[i])
                    break
        if not reason:
            try:
                g.paramSet("vcpus", "1")
            except:
                reason = "Error setting VCPUs to 1"
        if not reason:
            cpus = string.split(\
                g.host.execdom0("xm vcpu-list %u | grep -v \"^Name\" | "
                                "awk '{print $4}'" % (domid)))
            if cpus[1] != "-":
                reason = "Second CPU is not marked as offline (%s)" % (cpus[1])
        if not reason:
            time.sleep(30)
            c = g.getGuestVCPUs()
            if c != 1:
                reason = "Guest thinks it has %u CPUs, we asked for 1" % (c)
        if not reason:
            try:
                g.paramSet("vcpus", "2")
            except:
                reason = "Error setting VCPUs to 2"
        if not reason:
            cpus = string.split(\
                g.host.execdom0("xm vcpu-list %u | grep -v \"^Name\" | "
                                "awk '{print $4}'" % (domid)))
            if len(cpus) != 2:
                reason = "Guest did not have 2 VCPUs (%u)" % (len(cpus))
        if not reason:
            for i in range(len(cpus)):
                if not re.search(r"\d+", cpus[i]):
                    reason = "VCPU %u not assigned to physical CPU ('%s')." % \
                             (cpus[i])
                    break
        if not reason:
            time.sleep(30)
            c = g.getGuestVCPUs()
            if c != 2:
                reason = "Guest thinks it has %u CPUs, we asked for 2" % (c)
                
        if reason:
            self.testcaseResult("VCPU_change", "VCPU_change",
                                xenrt.RESULT_FAIL, reason)
        else:
            self.testcaseResult("VCPU_change", "VCPU_change",
                                xenrt.RESULT_PASS)

    def postRun(self):
        for g in self.guestsToClean:
            try:
                g.shutdown(force=True)
            except:
                pass
            g.poll("DOWN", 120, level=xenrt.RC_ERROR)
            g.uninstall()
            time.sleep(15)

class TCSMStress(xenrt.TestCase):

    def __init__(self, tcid="TCSMStress"):
        xenrt.TestCase.__init__(self, tcid)
        self.hostToClean = None

    def run(self, arglist=None):
        
        machine = "RESOURCE_HOST_0"
        diskspace = 40 * 1024
        
        if arglist and len(arglist) > 0:
            machine = arglist[0]
        host = xenrt.TEC().registry.hostGet(machine)
        self.hostToClean = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Get the test scripts
        testtar = xenrt.TEC().lookup("CLI_REGRESSION_TESTS", None)
        if not testtar:
            # Try the same directory as the ISO
            testtar = xenrt.TEC().getFile("cli-regress.tar.gz",
                                          "xe-phase-1/cli-regress.tar.gz")
        if not testtar:
            raise xenrt.XRTError("No CLI regression test tarball given")
        os.mkdir("%s/unpack" % (self.tec.getWorkdir()))
        xenrt.command("tar -zxf %s -C %s/unpack" %
                      (testtar, self.tec.getWorkdir()))

        # Copy the files to the server
        sftp = host.sftpClient()
        d = host.hostTempDir()
        sftp.copyTreeTo("%s/unpack" % (self.tec.getWorkdir()), d)

        # Figure out the disk sizes etc. to use based on what we have
        # available. Assume sizeinc is half of base1 and base1 is half
        # of base2. Therefore each parallel VM (there are 4) needs
        # 10 * sizeinc (CA-4965).
        sizeinc = diskspace/50
        size1 = sizeinc * 2
        size2 = sizeinc * 4

        # Build a command line to run the test on the server
        cmd = []
        cmd.append("%s/sm_stress.opt" % (d))
        cmd.append("-xe")
        cmd.append("xe")
        cmd.append("-base_size1 %u -base_size2 %u -size_inc %u" %
                   (size1, size2, sizeinc))
        resfile = "/tmp/smstress.out"
        cmd.append("2>&1 | tee %s" % (resfile))

        # Run the test on the server
        host.execdom0("echo %s | passwd --stdin root" %
                     (xenrt.TEC().lookup("DEFAULT_PASSWORD")))
        host.password = xenrt.TEC().lookup("DEFAULT_PASSWORD")
        host.execdom0("cd %s && %s" % (d, string.join(cmd)))

        # Pull back the log file
        lresfile = "%s/smstress.out" % (self.tec.getLogdir())
        sftp.copyFrom(resfile, lresfile)

        # Check for failures
        passed = False
        try:
            xenrt.command("grep -q FAILURE %s" % (lresfile))
            self.tec.reason("FAILURE found in test log")
        except:
            passed= True

        sftp.close()

        if not passed:
            raise xenrt.XRTFailure()

    def postRun(self):
        if self.hostToClean:
            # Put the root password back to what it was (assumes we have
            # SSH key trust)
            self.hostToClean.password = None
            p = xenrt.TEC().lookup("ROOT_PASSWORD")
            self.hostToClean.execdom0("echo %s | passwd --stdin root" % (p))
            self.hostToClean.password = p
            
            # Kill any left over domains
            self.hostToClean.uninstallAllGuests()

            # Put back the correct license
            self.hostToClean.license()

class TCQuicktest(xenrt.TestCase):

    def __init__(self, tcid="TCQuicktest"):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None
        self.isosr = None

    def prepare(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        self.host = host
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))

        # Set the quicktest-no-VDI_CREATE other-config key on existing ISO SRs
        for sr in host.getSRs(type="iso"):
            host.genParamSet("sr", sr, "other-config", "true",
                             "quicktest-no-VDI_CREATE")

        # Now create a temporary NFS ISO SR for quicktest to actually use
        nfs = xenrt.resources.NFSDirectory()
        isodir = xenrt.command("mktemp -d %s/isoXXXX" % (nfs.path()), strip = True)
        isosr = xenrt.lib.xenserver.ISOStorageRepository(self.host, "isosr")
        self.isosr = isosr
        server, path = nfs.getHostAndPath(os.path.basename(isodir))
        isosr.create(server, path)

    def run(self, arglist=None):
        host = self.host

        self.getLogsFrom(host)
        if host.execdom0("test -e /opt/xensource/debug/quicktest",
                         retval="code") != 0:
            xenrt.TEC().skip("No /opt/xensource/debug/quicktest")
            return
        try:
            host.execdom0("/opt/xensource/debug/quicktest -nocolour %s root %s" %
                          (host.getIP(), host.password),
                          timeout=3600)
        except xenrt.XRTFailure, e:
            if e.data:
                r = re.search(r"(Fatal error: .*)", e.data)
                if r:
                    raise xenrt.XRTFailure("quicktest failed: %s" %
                                           (r.group(1)))
                r = re.search(r"\*\*\* Some tests failed \*\*\*\s*(.*)",
                              e.data)
                if r:
                    raise xenrt.XRTFailure("quicktest failed: %s" %
                                           (r.group(1)))
            raise xenrt.XRTFailure("quicktest failed")

    def postRun(self):
        if self.isosr:
            try:
                self.isosr.remove()
            except:
                xenrt.TEC().warning("Exception removing temporary ISO SR")
        self.host.uninstallAllGuests()        


class TCQuicktestThinLVHD(TCQuicktest):
    """Run quicktest with thin-lvhd SR"""
    
    def prepare(self, arglist=[]):
        host = self.getDefaultHost()
        self.host = host
        sr = xenrt.lib.xenserver.ISCSIStorageRepository(host, "iscsisr", True)
        lun = xenrt.ISCSIVMLun()
        sr.create(lun, subtype="lvm", multipathing=None, noiqnset=True, findSCSIID=True)
        p = host.minimalList("pool-list")[0]
        host.genParamSet("pool", p, "default-SR", sr.uuid)


class TCUseWindowsCLI(xenrt.TestCase):

    def __init__(self, tcid="TCUseWindowsCLI"):
        xenrt.TestCase.__init__(self, tcid)
        
    def run(self, arglist=None):
        guest = None
        for arg in arglist:
            l = arg.split("=")
            if l[0] == "guest":
                guest = xenrt.TEC().registry.guestGet(l[1])
            elif l[0] == "config":
                matching = xenrt.TEC().registry.guestLookup(\
                            **xenrt.util.parseXMLConfigString(l[1]))
                for n in matching:
                    xenrt.TEC().comment("Found matching guest(s): %s" % (matching))
                if matching:
                    gname = matching[0] 
        if not guest:
            raise xenrt.XRTError("No Windows CLI guest specified.")
        xenrt.TEC().logverbose("Using guest %s for Windows CLI." % (guest.name))        

        if guest.getState() == "DOWN":
            xenrt.TEC().logverbose("Starting Windows CLI guest.")
            guest.start()
        guest.check()

        xenrt.TEC().registry.write("/xenrt/cli/windows", True) 
        xenrt.TEC().registry.write("/xenrt/cli/windows_guest", guest)
        xenrt.lib.xenserver.cli.clearCacheFor(guest.host.machine)

class TCUseLinuxCLI(xenrt.TestCase):
    
    def __init__(self, tcid="TCUseLinuxCLI"):
        xenrt.TestCase.__init__(self, tcid)

    def run(self, arglist=None):
        try:
            guest = xenrt.TEC().registry.read("/xenrt/cli/windows_guest")
            guest.shutdown()
        except:
            pass
        
        xenrt.TEC().registry.delete("/xenrt/cli/windows")
        xenrt.TEC().registry.delete("/xenrt/cli/windows_guest")
        xenrt.lib.xenserver.cli.clearCacheFor(guest.host.machine)

class TCWindowsCLI(xenrt.TestCase):

    def run(self, arglist=None):
        # Test basic functionality of the Windows CLI (install, start, 
        # shutdown, uninstall)

        host = self.getDefaultHost()
        
        # Install a VM to test
        guest = host.createGenericWindowsGuest()
        self.uninstallOnCleanup(guest)
        guest.installCarbonWindowsCLI()

        myguest = host.createGenericLinuxGuest(name="windowsclitestGuest", start=False)
        self.uninstallOnCleanup(myguest)
        
        # Build up standard parameters
        args = ["-s %s" % (host.getIP()), "-u root", "-pw %s" % (xenrt.TEC().lookup("ROOT_PASSWORD"))]

        # Now attempt to start
        startargs = ["vm-start","uuid=\"%s\"" % (myguest.getUUID())]

        guest.xmlrpcExec("c:\\windows\\xe.exe " + string.join(args) + " " + string.join(startargs))

        if not host.listDomains().has_key(myguest.getUUID()):
            raise xenrt.XRTFailure("Guest did not start as expected")

        # Now wait 2 minutes to allow it to boot etc
        time.sleep(120)

        stopargs = ["vm-shutdown","uuid=\"%s\"" % (myguest.getUUID()), "force=\"true\""]

        guest.xmlrpcExec("c:\\windows\\xe.exe " + string.join(args) + " " + string.join(stopargs))

        if host.listDomains().has_key(myguest.getUUID()):
            raise xenrt.XRTFailure("Guest still running after vm-shutdown")

        uninstargs = ["vm-uninstall","uuid=\"%s\"" % (myguest.getUUID()),"force=\"true\""]

        guest.xmlrpcExec("c:\\windows\\xe.exe " + string.join(args) + " " + string.join(uninstargs), timeout=3600)

        if host.listGuests().count("windowsclitestGuest"):
            raise xenrt.XRTFailure("Guest was not uninstalled from host by vm-uninstall")

class TCCLIAuth(xenrt.TestCase):

    def __init__(self, tcid="TCCLIAuth"):
        xenrt.TestCase.__init__(self, tcid)
        self.origpassword = None
        self.origusername = None
        self.cli = None
        self.host = None

    def run(self, arglist=None):
        
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]
            
        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        self.host = host

        cli = host.getCLIInstance()
        username = cli.username
        password = cli.password
        self.cli = cli
        self.origpassword = password
        self.origusername = username

        xenrt.TEC().logverbose("Testing with correct password and username.") 
        cli.execute("vm-list")

        xenrt.TEC().logverbose("Testing with incorrect password.") 
        thrown = False
        try:
            cli.password = "foo"
            cli.execute("vm-list")
        except:
            cli.password = password
            thrown = True
        if not thrown:
            raise xenrt.XRTFailure("CLI call suceeded using incorrect password.")

        xenrt.TEC().logverbose("Testing with incorrect username.")
        thrown = False
        try:
            cli.username = "foo"
            cli.execute("vm-list")
        except:
            cli.username = username
            thrown = True
        if not thrown:
            raise xenrt.XRTFailure("CLI call suceeded using incorrect username.")

        xenrt.TEC().logverbose("Changing password.")
        cli.execute("user-password-change old=%s new=%s" % (password, "xenrt"))
        cli.password = "xenrt"

        xenrt.TEC().logverbose("Testing with new password.")
        cli.execute("vm-list")

        xenrt.TEC().logverbose("Testing with incorrect old password.")
        thrown = False
        try:
            cli.password = password 
            cli.execute("vm-list")
        except:
            cli.password = "xenrt"
            thrown = True
        if not thrown:
            raise xenrt.XRTFailure("CLI call suceeded using old password.")

        xenrt.TEC().logverbose("Resetting password.")
        cli.execute("user-password-change old=%s new=%s" % (cli.password, password))

    def postRun(self):
        if self.cli and self.origpassword:
            self.cli.password = self.origpassword
        if self.cli and self.origusername:
            self.cli.username = self.origusername
        if self.origpassword:
            self.host.execdom0("echo %s | passwd --stdin root" %
                               (self.origpassword))

class TCCLICrashdumpUpload(xenrt.TestCase):
    """Test the host-crashdump-upload command"""

    def __init__(self, tcid="TCCLICrashdumpUpload"):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None

    def run(self, arglist=None):

        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)
        self.host = host

        # Check we can get out
        rc = host.execdom0("wget -O /dev/null -q http://www.xensource.com/",
                           retval="code")
        if rc > 0:
            xenrt.TEC().skip("Unable to establish http connection, assuming no "
                             "internet connection...")
            return

        workdir = xenrt.TEC().getWorkdir()

        # Are there any crashdumps (if so we don't need to generate one)
        cds = host.listCrashDumps()
        if len(cds) == 0:
            generated = True
            # Generate a crashdump...
            try:
                host.execdom0("sleep 5 && echo c > /proc/sysrq-trigger &",timeout=30)
            except:
                # We expect to lose the SSH connection, as this command crashes the
                # host...
                pass

            # Wait for the host to reboot
            host.waitForSSH(1200, desc="Post crash reboot")

            # Confirm there is a crashdump
            cds = host.listCrashDumps()
            if len(cds) == 0:
                raise xenrt.XRTError("Crashing host did not generate a "
                                     "crashdump!")
        else:
            generated = False

        xenrt.TEC().comment("crashdump UUID: %s" % (cds[0]))

        # Now try the upload
        host.uploadCrashDump(cds[0])

        # Get the name
        # This is a bit nasty and is likely to go wrong on hosts with existing
        # dumps, hopefully a solution to CA-8453 will mean we can make this 
        # nicer
        dumps = host.execdom0("ls -t /var/crash")
        dumpsentries = dumps.split()
        cdname = dumpsentries[0]
        xenrt.TEC().comment("crashdump directory believed to be %s" % (cdname))
#        cdname = host.parseListForParam("host-crashdump-list", cds[0], 
#                                        "timestamp")

        # Check it got through
        sftp = xenrt.ssh.SFTPSession("support.xensource.com",
                            username=xenrt.TEC().lookup("CDUMP_USERNAME", None),
                            password=xenrt.TEC().lookup("CDUMP_PASSWORD", None),
                            level=xenrt.RC_ERROR)

        try:
            sftp.copyFrom("~ftp/uploads/%s-%s" % (host.getUUID(),cdname),
                          "%s/crashdump" % (workdir))
        except:
            raise xenrt.XRTFailure("Crashdump does not appear to have been "
                                   "uploaded")

        # See if it matches the actual crashdump on the host...
        
        # Generate md5sums on the host
        md5s = host.execdom0("cd /var/crash/%s; md5sum *" % cdname)
        
        # See if they match
        f = file("%s/cdump_md5s" % (workdir),"w")
        f.write(md5s)
        f.close()
        xenrt.util.command("tar -xzf -C %s/tmp %s/crashdump" % (workdir,workdir))
        
        rc = xenrt.util.command("cd %s/tmp/var/crash/%s; "
                                "md5sum -c %s/cdump_md5s" % (workdir,cdname,
                                                             workdir))
        if rc > 0:
            raise xenrt.XRTFailure("Uploaded crashdump does not match original")

        # If we generated it, delete the crashdump so we don't think it's a 
        # real crash when getting logs from the host
        if generated:
            host.destroyCrashDump(cds[0])

class TCBugReportUpload(xenrt.TestCase):

    def __init__(self, tcid="TCBugReportUpload"):
        xenrt.TestCase.__init__(self, tcid)
        self.host = None

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry." %
                                 (machine))
        self.getLogsFrom(host)
        self.host = host
    
        host.uploadBugReport()
        host.checkBugReport()

class TCDom0FullPatchApply(xenrt.TestCase):

    def run(self, arglist=None):
        # proper error message is There is not enough space to upload the update
        host = self.getDefaultHost()
        path = host.getTestHotfix(2)
        hotfixPath = "/tmp/test-hotfix.unsigned"
        sftp = host.sftpClient()
        try:
            xenrt.TEC().logverbose('About to copy "%s to "%s" on host.' \
                                        % (path, hotfixPath))
            sftp.copyTo(path, hotfixPath)
        finally:
            sftp.close()
        sha1 = host.execdom0("sha1sum %s" % hotfixPath).strip()
        host.execdom0('echo %s > /tmp/fist_allowed_unsigned_patches' % sha1)

        host.execdom0("dd count=1 if=/dev/zero of=/root/filldisktmp bs=5M") 
        try:
            host.execdom0("dd if=/dev/zero of=/root/filldisk bs=1M")
        except:
            pass
        
        host.execdom0("rm -rf /root/filldisktmp")

        try:
            patchUUID = host.execdom0("xe patch-upload file-name=%s" % hotfixPath).strip()
            raise xenrt.XRTFailure("No Error message raised")
        except Exception, e:
            if not "not enough space" in e.data:
                xenrt.TEC().logverbose("Error message is not same, its %s" % (str(e)))
                raise xenrt.XRTFailure("Error message is not correct, its %s" % (str(e)))

class TCPatchApply(xenrt.TestCase):
    """Verify the application of example patches and the prechecking of example patches with negative expected outcomes."""

    def patch1(self):
        try:
            self.host.applyPatch(self.host.getTestHotfix(1), returndata=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

        if self.host.execdom0("test -e /root/hotfix-test1", retval="code") != 0:
            raise xenrt.XRTFailure("/root/hotfix-test1 does not exist after applying hotfix1")
    
    def patch2(self):
        try:
            self.host.applyPatch(self.host.getTestHotfix(2), returndata=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

        if not isinstance(self.host, xenrt.lib.xenserver.DundeeHost) and self.host.execdom0("rpm -q Deployment_Guide-en-US", retval="code") != 0:
            raise xenrt.XRTFailure("Deployment_Guide-en-US RPM not found after applying hotfix2")
    
    def patch3(self):
        try:
            self.host.applyPatch(self.host.getTestHotfix(3), returndata=True)
        except xenrt.XRTFailure, e:
            if not re.search("It is doomed to failure", e.data):
                raise xenrt.XRTFailure("hotfix3 apply error message did not contain 'It is doomed to failure'")
        else:
            raise xenrt.XRTFailure("hotfix3 apply did not fail")

    def patch4(self):
        try:
            self.host.applyPatch(self.host.getTestHotfix(4), returndata=True)
        except xenrt.XRTFailure, e:
            if not re.search("the server is of an incorrect version", e.data):
                raise xenrt.XRTFailure("hotfix4 apply error message did not contain 'the server is of an incorrect version'")
        else:
            raise xenrt.XRTFailure("hotfix4 apply did not fail")

        # Check the body wasn't executed anyway (XRT-5112)
        rc = self.host.execdom0("ls /root/hotfix-test4", retval="code")
        if rc == 0:
            raise xenrt.XRTFailure("Body of patch executed even though precheck failed")

    def patch5(self):
        try:
            self.host.applyPatch(self.host.getTestHotfix(5), returndata=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

    def run(self, arglist=None):
        if arglist and len(arglist) > 0:
            machine = arglist[0]
            self.host = xenrt.TEC().registry.hostGet(machine)
            if not self.host:
                raise xenrt.XRTError("Unable to find host %s in registry." % machine)
            self.getLogsFrom(self.host)
        else:
            self.host = self.getDefaultHost()

        self.runSubcase("patch1", (), "TCPatchApply", "Test1")
        self.runSubcase("patch2", (), "TCPatchApply", "Test2")
        self.runSubcase("patch3", (), "TCPatchApply", "Test3")
        self.runSubcase("patch4", (), "TCPatchApply", "Test4")
        self.runSubcase("patch5", (), "TCPatchApply", "Test5")

class TC7350(xenrt.TestCase):
    """The update-upload command for OEM updating should result in a
    suitable error on non-OEM builds"""

    def run(self, arglist):
        host = self.getDefaultHost()

        # Extract the tarball to get the sample patch
        workdir = xenrt.TEC().getWorkdir()
        xenrt.getTestTarball("patchapply",extract=True,directory=workdir)

        # Check that OEM edition command xe update-upload fails
        cli = host.getCLIInstance()
        allowed = True
        try:
            result = cli.execute("update-upload",
                                 "file-name=%s/patchapply/oemupdate.patch "
                                 "host-uuid=%s" % 
                                 (workdir,host.getMyHostUUID()))
        except xenrt.XRTFailure, e:
            allowed = False
            if not "ONLY_ALLOWED_ON_OEM_EDITION" in e.reason:
                if not e.reason.startswith("Unknown command"):
                    xenrt.TEC().warning("update-upload failed but with incorrect "
                                        "response: %s" % (e.reason))
                    self.setResult(xenrt.RESULT_PARTIAL)            

        if allowed:
            raise xenrt.XRTFailure("update-upload command was allowed on non OEM edition")

class TC7351(xenrt.TestCase):
    """Perform a loop of 100 patch-upload/patch-destroy cycles"""

    def run(self, arglist):
        host = self.getDefaultHost()

        patchfile = host.getTestHotfix(1)
        xenrt.TEC().logverbose("Performing patch-upload/patch-destroy loop")
        
        for i in range(100):
            xenrt.TEC().logverbose("Iteration " + str(i))
            uuid = host.uploadPatch(patchfile)
            host.destroyPatch(uuid)

class TCHotfix(xenrt.TestCase):
    """Verify a particular hotfix can or cannot (as specified) be applied to a host in a certain configuration."""

    def run(self, arglist):
        negative = False
        if not arglist or len(arglist) == 0:
            raise xenrt.XRTError("No hotfix specified")
        hotfix = arglist[0]
        if len(arglist) > 1 and arglist[1] == "negative":
            negative = True
        
        host = self.getDefaultHost()
        patches = host.minimalList("patch-list")
        host.execdom0("xe patch-list")
        xenrt.TEC().comment("Host has %u existing patches" % (len(patches)))
        
        if negative:
            worked = False
            try:
                result = host.applyPatch(xenrt.TEC().getFile(hotfix),
                                         returndata=True)
                worked = True
            except xenrt.XRTFailure, e:
                if not re.search("prerequisite patches are missing", e.data):
                    raise xenrt.XRTFailure("Did not get expected error "
                                           "message when applying patch",
                                           e.data)
            if worked:
                raise xenrt.XRTFailure("Hotfix applied when it should not have")
        else:
            host.applyPatch(xenrt.TEC().getFile(hotfix))

            patches2 = host.minimalList("patch-list")
            host.execdom0("xe patch-list")
            if len(patches2) != (len(patches) + 1):
                raise xenrt.XRTFailure("Patch does not show in list after applying")

class TCUpdate(xenrt.TestCase):
    """Verify a particular OEM update can be applied to a host in a certain configuration."""

    def run(self, arglist):
        if not arglist or len(arglist) == 0:
            raise xenrt.XRTError("No update specified")
        update = arglist[0]

        host = self.getDefaultHost()
        patches = host.minimalList("patch-list")
        host.execdom0("xe patch-list")
        xenrt.TEC().comment("Host has %u existing patches" % (len(patches)))

        xenrt.TEC().progress("Applying OEM update %s" % (update))
        updatefile = xenrt.TEC().getFile(update)
        if updatefile[-4:] == ".bz2":
            newfile = "%s/update_%s" % (xenrt.TEC().getWorkdir(),
                                        host.getName())
            shutil.copyfile(updatefile, "%s.bz2" % (newfile))
            xenrt.util.command("bunzip2 %s.bz2" % (newfile))
            try:
                host.applyOEMUpdate(newfile)
            finally:
                os.unlink(newfile)
        else:
            host.applyOEMUpdate(updatefile)
        host.reboot()

        patches2 = host.minimalList("patch-list")
        host.execdom0("xe patch-list")
        if len(patches2) <= len(patches):
            raise xenrt.XRTFailure("Patch does not show in list after applying")

        for p in patches:
            if not p in patches2:
                raise xenrt.XRTFailure("Patch %s missing after update" % (p))

