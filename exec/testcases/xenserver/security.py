#
# XenRT: Test harness for Xen and the XenServer product family
#
# Security tests.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, os.path, xml.dom.minidom, re, time
import xenrt
from tc.cc import _CCSetup
from xenrt.lazylog import step

class TCOpenPorts(_CCSetup):
    LICENSE_SERVER_REQUIRED = False

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCOpenPorts")
        self.expected = []
        self.allowedservices = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        # Select allowed ports by product
        self.expected = string.split(xenrt.TEC().lookup("NMAP_ONLY_PORTS", ""))
        if len(self.expected) == 0:
            self.expected.extend(string.split(host.lookup("NMAP_ALLOWED_PORTS",
                                                          "tcp/22 tcp/6936")))
        self.allowedservices.extend(\
            string.split(host.lookup("NMAP_ALLOWED_SERVICES", "nlockmgr")))
        
        # Run nmap to scan open ports
        outfile = "%s/nmap.txt" % (self.tec.getLogdir())
        xmlfile = "%s/nmap.xml" % (self.tec.getLogdir())
        xenrt.nmap(host.getIP(), xmlfile, outfile)
        if not os.path.exists(xmlfile):
            raise xenrt.XRTError("nmap output file not found")

        # Parse nmap output
        ports = []
        portlist = []
        dom = xml.dom.minidom.parse(xmlfile)
        for i in dom.childNodes:
            if i.nodeType == i.ELEMENT_NODE and i.localName == "nmaprun":
                for c in i.childNodes:
                    if c.nodeType == c.ELEMENT_NODE and c.localName == "host":
                        for x in c.childNodes:
                            if x.nodeType == x.ELEMENT_NODE and \
                               x.localName == "ports":
                                for p in x.childNodes:
                                    if p.nodeType == p.ELEMENT_NODE and \
                                       p.localName == "port":
                                        proto = p.getAttribute("protocol")
                                        port = p.getAttribute("portid")
                                        service = "UNKNOWN"
                                        state = "UNKNOWN"
                                        for z in p.childNodes:
                                            if z.nodeType == z.ELEMENT_NODE \
                                               and z.localName == "service":
                                                service = z.getAttribute("name")
                                            elif z.nodeType == z.ELEMENT_NODE \
                                                 and z.localName == "state":
                                                state = z.getAttribute("state")
                                       
                                        ports.append(("%s/%s" % (proto, port),
                                                      service,
                                                      state))
                                        portlist.append("%s/%s" % (proto, port))
                                       
        self.tec.logverbose("Parsed ports: %s" % (`ports`))

        # Check expected open ports are open
        passed = True
        for i in self.expected:
            if re.search(r"^\(.+\)$", i):
                # Non-compulsory port
                pass
            elif not i in portlist:
                self.tec.reason("Port %s is not open" % (i))
                passed = False
            else:
                self.tec.comment("Expected open port %s found to be open" %
                                 (i))

        # Check for any unexpected open ports
        for i in ports:
            port, service, state = i
            if state == "open" or state == "UNKNOWN":
                if (not port in self.expected) and \
                       (not "(%s)" % (port) in self.expected):
                    if not service in self.allowedservices:
                        self.tec.reason("Unexpected port %s (%s) is open" %
                                        (port, service))
                        passed = False
                    else:
                        self.tec.comment("Allowed service %s found on port %s"
                                         % (service, port))

        if not passed:
            raise xenrt.XRTFailure()

class TCCA9621(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCCA9621")

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        if isinstance(host, xenrt.lib.xenserver.TampaHost):
            g = host.createBasicGuest(distro='centos54')
        else:
            g = host.createGenericLinuxGuest()
        self.uninstallOnCleanup(g)

        host.execdom0("rm -f /tmp/CA-9621")

        # Tweak guest grub config to perform exploit
        g.execguest("mv /boot/grub/menu.lst /boot/grub/menu.lst.orig")
        g.execguest("sed -re's/^default.*$/default \"\\+str\\(0\\*os\\.system\\(\" touch \\/tmp\\/CA-9621 \"\\)\\)\\+\"/' < /boot/grub/menu.lst.orig > /boot/grub/menu.lst")
        g.execguest("cat /boot/grub/menu.lst")

        # Shut down and restart guest, check for exploit
        g.shutdown()
        e = None
        try:
            g.start()
        except xenrt.XRTFailure, e:
            e = e
        if host.execdom0("test -e /tmp/CA-9621", retval="code") == 0:
            raise xenrt.XRTFailure("CA-9621")
        if not e:
            xenrt.TEC().warning("No exception raised, pygrub might have "
                                "changed its behavior.")
        elif not (e.data and
                  re.search(r"The bootloader returned an error", e.data)):
            xenrt.TEC().warning("Unexpected error message, xapi might have "
                                "changed its behavior.")

class TCCA10038(xenrt.TestCase):

    def __init__(self):
        xenrt.TestCase.__init__(self, "TCCA10038")
        self.guestsToClean = []

    def run(self, arglist=None):
        machine = "RESOURCE_HOST_0"
        if arglist and len(arglist) > 0:
            machine = arglist[0]

        host = xenrt.TEC().registry.hostGet(machine)
        if not host:
            raise xenrt.XRTError("Unable to find host %s in registry" %
                                 (machine))
        self.getLogsFrom(host)

        host.execdom0("rm -f /tmp/CA-10038")

        for be in ["iso"]:
            cli = host.getCLIInstance()
            try:
                cli.execute("sr-create",
                            "type=%s "
                            "device-config-location=\"\\$(touch /tmp/CA-10038)\" "
                            "name-label=CA10038%s" % (be, be))
            except Exception, e:
                xenrt.TEC().logverbose("Good, got an exception: %s" % (str(e)))
            if host.execdom0("test -e /tmp/CA-10038", retval="code") == 0:
                raise xenrt.XRTFailure("CA-10038")

class TC8163(xenrt.TestCase):

    VMNAME = "Windows-VM-with-drivers"

    def __init__(self):
        xenrt.TestCase.__init__(self, "TC8163")

    def run(self, arglist=None):
        self.host = self.getDefaultHost()
        self.client = self.getGuest(self.VMNAME)
        if self.client.getState() != "UP":
            self.client.start()
        self.guest = self.host.createGenericLinuxGuest() 
        self.getLogsFrom(self.guest)
        self.uninstallOnCleanup(self.guest)
    
        xsclipath = "c:\\program files\\citrix\\xentools"
        if not self.client.xmlrpcDirExists(xsclipath):
            xsclipath = "c:\\program files (x86)\\citrix\\xentools"
            if not self.client.xmlrpcDirExists(xsclipath):
                raise xenrt.XRTError("Couldn't find XenTools directory on %s." % 
                                     (self.client.getName()))
        vdiuuid = self.guest.getDiskVDIUUID(0)
        data = self.client.xmlrpcExec("\"%s\"\\xenstore_client write /vss/%s/snapshot/%s \"\"" %
                                      (xsclipath, 
                                       self.guest.getUUID(), 
                                       vdiuuid), 
                                       returndata=True,
                                       returnerror=False)
        if not re.search("Access is denied", data):
            xenrt.TEC().logverbose("XenStore write returned: %s" % (data))
            xenrt.TEC().logverbose(self.guest.listVBDs())
            raise xenrt.XRTFailure("XenStore CLI call succeeded!")
        
        xenrt.TEC().progress("XenStore CLI call failed as expected.")

        currentvdiuuid = self.guest.getDiskVDIUUID(0)
        if not currentvdiuuid == vdiuuid:
            raise xenrt.XRTFailure("VDI UUIDs don't match. (%s != %s)" % 
                                   (currentvdiuuid, vdiuuid))

class _TCXSA(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        
        if isinstance(self.host, xenrt.lib.xenserver.MNRHost) and self.host.isCCEnabled():
            self.host.disableCC()
    
    def checkHost(self):
        try:
            for i in range(30):
                self.host.execdom0("xe vm-list", timeout=30)
                time.sleep(10)
        except:
            # so if the host can't be reached, then wait until it comes back
            # and then rethrow the exception.
            
            for i in range(1000):
                try:
                    self.host.execdom0("xe vm-list", timeout=30)
                except:
                    time.sleep(10)
                else:
                    # the host has come back. Now raise the exception.
                    raise
                    
            self.host.execdom0("xe vm-list")
    
    def replaceHvmloader(self, path):
        """Replace hvmloader with file at given 'path'"""
        self.hvmloaderPath = self.host.execdom0("find /usr/ -type f -name hvmloader").strip()
        self.host.execdom0("cp -f {0} {0}.backup".format(self.hvmloaderPath))
        hvmloader = xenrt.TEC().getFile(path)
        sftp = self.host.sftpClient()
        try:
            xenrt.TEC().logverbose('About to copy "%s to "%s" on host.' \
                                        % (hvmloader, self.hvmloaderPath))
            sftp.copyTo(hvmloader, self.hvmloaderPath)
        finally:
            sftp.close()

class TCXSA24(_TCXSA):
    VULN = 24
 
    def getCfg(self):
        return """name="%s"
builder="generic"
kernel="/root/mini-os-xsa.gz"
extra="mode=general"
""" % self.name
        
    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        self.name = xenrt.randomGuestName()
        
        url = "http://hg.uk.xensource.com/closed/xen-hypercall-fuzzer.hg/raw-file/tip/misc/mini-os-xsa%d.gz" % (self.VULN)
        
        self.host.execdom0('cd /root && wget "%s"' % url)
        self.host.execdom0('mv /root/%s /root/mini-os-xsa.gz' % (os.path.basename(url)))
        
        if isinstance(self.host, xenrt.lib.xenserver.ClearwaterHost):
            self.host.execdom0("echo '%s' > /root/minios.cfg" % self.getCfg())
            return
        
        # hack the DLVM script so that it uses mini-os for its kernel
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            insert = 'run("cp \/root\/mini-os-xsa.gz %s\/boot\/%s" % (mountpoint, "xenu-linux-2.6.18.8.xs6.1.0.16.450"))'
        elif isinstance(self.host, xenrt.lib.xenserver.BostonHost) and self.host.productVersion == "Sanibel":
            insert = 'run("cp \/root\/mini-os-xsa.gz %s\/boot\/%s" % (mountpoint, "xenu-linux-2.6.18.8.xs6.0.2.16.450"))'
        elif isinstance(self.host, xenrt.lib.xenserver.BostonHost):
            insert = 'run("cp \/root\/mini-os-xsa.gz %s\/boot\/%s" % (mountpoint, "xenu-linux-2.6.18.8.xs6.0.0.16.450"))'
        elif isinstance(self.host, xenrt.lib.xenserver.MNRHost) and (self.host.productVersion == "Cowley" or self.host.productVersion == "Oxford"):
            insert = 'run("cp \/root\/mini-os-xsa.gz %s\/boot\/%s" % (mountpoint, "xenu-linux-2.6.18.8.xs5.6.100.16.450"))'
        elif isinstance(self.host, xenrt.lib.xenserver.MNRHost):
            insert = 'run("cp \/root\/mini-os-xsa.gz %s\/boot\/%s" % (mountpoint, "xenu-linux-2.6.18.8.xs5.6.0.15.449"))'
        elif isinstance(self.host, xenrt.lib.xenserver.Host) and self.host.productVersion == "George":
            insert = 'run("cp \/root\/mini-os-xsa.gz %s\/boot\/%s" % (mountpoint, "xenu-linux-2.6.18.8.xs5.5.0.13.442"))'
        elif isinstance(self.host, xenrt.lib.xenserver.Host):
            insert = 'run("cp \/root\/mini-os-xsa.gz %s\/boot\/%s" % (mountpoint, "xenu-linux-2.6.18.8.xs5.0.0.10.439"))'
        
        self.host.execdom0("sed -i '/root.tar.bz2/ s/$/; %s/' /opt/xensource/packages/post-install-scripts/debian-etch" % insert)
        self.host.execdom0("cat /opt/xensource/packages/post-install-scripts/debian-etch")
    
    def run(self, arglist=None):
        
        if isinstance(self.host, xenrt.lib.xenserver.ClearwaterHost):
            self.host.execdom0("xl create /root/minios.cfg")
            return
        if isinstance(self.host, xenrt.lib.xenserver.MNRHost):
            template = "Demo Linux VM"
        else:
            template = "Debian Etch 4.0"
        
        vm = self.host.execdom0("xe vm-install new-name-label=XSA%d template-name=\"%s\"" % (self.VULN, template)).strip()
        self.host.execdom0("xe vm-start uuid=%s" % vm)
        
        self.checkHost()
    
class TCXSA23(_TCXSA):
    
    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        self.replaceHvmloader("http://hg.uk.xensource.com/closed/xen-hypercall-fuzzer.hg/raw-file/tip/misc/hvmloader-xen-4.1-xsa23")
    
    def run(self, arglist=None):
        vm = self.host.execdom0("xe vm-install new-name-label=vm template-name=\"Other install media\"").strip()
        self.host.execdom0("xe vm-cd-add uuid=%s cd-name=\"ws08sp2-x86.iso\" device=3" % vm)
        
        try:
            self.host.execdom0("xe vm-start uuid=%s" % vm, timeout=30)
        except:
            # need to catch this here, as we always want checkHost to be called
            # below as this waits for the host to come back.
            pass
        
        self.checkHost()
            
class _TCXSA2x(_TCXSA):

    VULN = 20
    
    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        
        # this is a debian 6 HVM VM with stuff from 
        # http://hg.uk.xensource.com/closed/xen-hypercall-fuzzer.hg/file/tip
        # copied on to it and then compiled.
        dfMount = '/tmp/xsaXVA'
        distFiles = xenrt.TEC().lookup('EXPORT_DISTFILES_NFS', None)
        if not distFiles:
            raise xenrt.XRTError("EXPORT_DISTFILES_NFS not defined")

        self.host.execdom0("mkdir -p %s" % (dfMount))
        self.host.execdom0("mount %s %s" % (distFiles, dfMount))

        try:
            xenHypFuzzDir = os.path.join(dfMount, 'xen-hyp-fuzzer')
            xvas = self.host.execdom0("ls %s" % (os.path.join(xenHypFuzzDir, '*.xva'))).split()
            xenrt.TEC().logverbose("Found xvas: %s in %s" % (",".join(xvas), xenHypFuzzDir))

            # TODO - Handle >1 XVA
            xsaXVA = xvas[0]
            xenrt.TEC().logverbose("Importing file %s..." % (os.path.basename(xsaXVA)))

            self.guest = self.host.guestFactory()("XSA%d" % self.VULN, host=self.host, password="xensource")
            self.guest.enlightenedDrivers = False
            self.guest.windows = False
            self.guest.importVM(self.host, xsaXVA, sr=self.host.lookupDefaultSR(), imageIsOnHost=True)
            self.guest.enlightenedDrivers = False
            self.guest.windows = False
        finally:
            self.host.execdom0("umount %s" % (dfMount))

        self.guest.start()
        self.guest.execguest("apt-get install mercurial --force-yes -y")
        self.guest.execguest("cd /root && hg clone http://hg.uk.xensource.com/closed/xen-hypercall-fuzzer.hg", timeout=3600)
        self.guest.execguest("cd /root/xen-hypercall-fuzzer.hg/kernel && make")
        self.guest.execguest("cd /root/xen-hypercall-fuzzer.hg/misc && make")
        self.guest.execguest("cd /root/xen-hypercall-fuzzer.hg/kernel && make insert")
        
        if xenrt.TEC().lookup("PRODUCT_VERSION") == "SanibelCC":
            #For Sweeney (NPRI>=1/NSEC>=1/IPRI>=1)
            self.guest.removeVIF("eth0")
            bridge = self.host.parseListForOtherParam("network-list", "name-label", "Guest NW 0", "bridge")
            self.guest.createVIF("eth0", bridge)
    
    def run(self, arglist=None):
        self.guest.execguest("/root/xen-hypercall-fuzzer.hg/misc/vuln-test %d > /dev/null 2>&1 </dev/null &" % self.VULN)
        self.checkHost()
                    
    def postRun(self):
        self.guest.shutdown(force=True)

class TCXSA20(_TCXSA2x):
    VULN = 20
    
class TCXSA21(_TCXSA2x):
    VULN = 21
    
class TCXSA22(_TCXSA2x):
    VULN = 22

class TCXSA26(_TCXSA2x):
    VULN = 26

    def run(self, arglist=None):
        self.guest.execguest("cd /root/xen-hypercall-fuzzer.hg/kernel && make insert")
        self.guest.execguest("/root/xen-hypercall-fuzzer.hg/misc/vuln-test %d > /dev/null 2>&1 </dev/null &" % self.VULN)

        time.sleep(30)
        
        # Restart the VM and verify that the domain is removed.
        preRebootDomId = self.guest.getDomid()

        self.guest.lifecycleOperation("vm-reboot", force=True)

        for uuid, domainData in self.host.listDomains().iteritems():
            if domainData[0] == preRebootDomId:
                xenrt.TEC().logverbose("pre reboot DomID not removed.  UUID: %s, DomainData: %s" % (uuid, domainData))
                raise xenrt.XRTFailure("pre reboot DomID not removed")
        
class TCXSA30(_TCXSA2x):
    VULN = 30
    
class TCXSA31(_TCXSA2x):
    VULN = 31

    def run(self, arglist=None):
        self.guest.execguest("cd /root/xen-hypercall-fuzzer.hg/kernel && make insert")
        rData = self.guest.execguest("/root/xen-hypercall-fuzzer.hg/misc/vuln-test %d" % self.VULN).split('\n')

        failures = filter(lambda x:'Test failed' in x, rData)
        if len(failures) != 0:
            raise xenrt.XRTFailure("XSA Test failed with error(s): %s" % (failures)) 

class TCXSA29(TCXSA24):
    VULN = 29

    def prepare(self, arglist):
        host = self.getDefaultHost()
        self.name = xenrt.randomGuestName()
        xenVersion = host.getInventoryItem('XEN_VERSION')
        xenrt.TEC().logverbose("Found XEN version: %s" % xenVersion)
        xenMapFile = host.execdom0("""find /boot/xen-%s* | grep '\.map' | grep -v '\-d'""" % xenVersion).strip()
        xenMapLine = host.execdom0('grep " nmi$" %s' % xenMapFile)
        xenrt.TEC().logverbose("Found NMI line from map file: %s" % (xenMapLine))
        self.nmiAddr = '0x' + xenMapLine.split()[0]

        TCXSA24.prepare(self, arglist)
    
    
    def getCfg(self):
        return """name="%s"
builder="generic"
kernel="/root/mini-os-xsa.gz"
extra="mode=general xsa29_addr=%s"
""" % (self.name, self.nmiAddr)

    def run(self, arglist=None):
        
        if isinstance(self.host, xenrt.lib.xenserver.ClearwaterHost):
            self.host.execdom0("xl create /root/minios.cfg")
            domId = int(self.host.execdom0("xl domid %s" % self.name).strip())
        else:
            template = "Debian Etch 4.0"
            if isinstance(self.host, xenrt.lib.xenserver.MNRHost):
                template = "Demo Linux VM"
            
            vm = self.host.guestFactory()('XSA%d' % self.VULN, template, self.host)
            vm.createGuestFromTemplate(vm.template, None)
            vm.setBootParams('xsa29_addr=%s' % (self.nmiAddr))
            vm.start()
            domId = vm.getDomid()

        self.checkHost()
        
        if not "Fault on addr - Vulnerability seems fixed" in self.host.guestConsoleLogTail(domId, lines=100):
            raise xenrt.XRTFailure("XSA-29 not reported as fixed.")

class TCXSA44(TCXSA24):
    VULN = 44
    
class TCXSA55(TCXSA24):
    """XenServer should refuse to boot a VM with an invalid kernel"""
    VULN = 55

    def run(self, arglist):
        try:
            TCXSA24.run(self, arglist)
        except xenrt.XRTFailure, e:
            if "Xen will only load images" in str(e.data):
                xenrt.TEC().logverbose("Error Message while starting a VM with invalid kernel: %s" % str(e.data))
                pass
            else:
                raise xenrt.XRTFailure("Unexpected error message while starting a VM with invalid kernel", data=str(e.data))
        else:
            raise xenrt.XRTFailure("Succeeded to start a VM with an invalid kernel")

class TCXSA87(TCXSA29):
    """Test to verify XSA-87"""
    # Jira TC-23743
    
    VULN = 87

    def run(self, arglist=None):
        
        self.host.execdom0("xl create /root/minios.cfg")
        self.checkHost()
        
        if not self.host.guestconsolelogs:
            raise xenrt.XRTFailure("No guest console logs")
        filename = "%s/console.*.log" % (self.host.guestconsolelogs)
        logs = self.host.execdom0("tail -n 100 %s" % (filename))
        
        if "Xen appears still vulnerable to XSA-87!" in logs:
            raise xenrt.XRTFailure("XSA-87 not reported as fixed.")
        elif "XSA-87 appears fixed" in logs:
            xenrt.TEC().logverbose("XSA-87 fixed")
        else:
            raise xenrt.XRTFailure("Unexpected output. 'XSA-87' not found in logs")
            
class TCXSA111(_TCXSA):
    """Test to verify XSA-111"""
    # Jira TC-23744

    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        self.replaceHvmloader("/usr/groups/xenrt/xsa_test_files/test-hvm-xsa-111")

    def run(self, arglist=None):
        vm = self.host.execdom0("xe vm-install new-name-label=vm template-name=\"Other install media\"").strip()
        self.host.execdom0("xe vm-cd-add uuid=%s cd-name=\"win7-x86.iso\" device=3" % vm)
        self.host.execdom0("xe vm-start uuid=%s" % vm, timeout=30)

        self.checkHost()

        xenrt.TEC().logverbose("Expected output: Host didn't crash")

    def postRun(self):
        self.host.execdom0("cp -f {0}.backup {0}".format(self.hvmloaderPath))

class TCXSA112(_TCXSA):
    """Test to verify XSA-112"""
    # Jira TC-23745
    
    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        #change log level for pre dundee hosts
        if not isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            self.host.execdom0("sed -e 's/\(append .*xen\S*.gz\)/\\0 loglvl=all guest_loglvl=all/' /boot/extlinux.conf > tmp && mv tmp /boot/extlinux.conf -f")
        self.host.reboot()
        self.replaceHvmloader("/usr/groups/xenrt/xsa_test_files/test-hvm-xsa-112")
        
    def run(self, arglist=None):
        vm = self.host.execdom0("xe vm-install new-name-label=vm template-name=\"Other install media\"").strip()
        self.host.execdom0("xe vm-cd-add uuid=%s cd-name=\"win7-x86.iso\" device=4" % vm)
        self.host.execdom0("xe vm-start uuid=%s" % vm, timeout=30)
    
        self.checkHost()
        serlog = string.join(self.host.machine.getConsoleLogHistory(), "\n")
        xenrt.TEC().logverbose(serlog)
        
        if "All done: Poisoned value found as expected" in serlog:
            xenrt.TEC().logverbose("Expected output: Found 'Poisoned value found as expected' in serial log")
        elif "Test failed: Expected to find poisoned value" in serlog:
            raise xenrt.XRTFailure("XSA-112 not fixed.Found 'Test failed: Expected to find poisoned value' in logs")
        else:
            #Workaround for CA-159772: Sometimes host serial log is not available for a machine
            #Raise an error in that case.
            if "not found" in serlog or "Enter `^Ec?' for help" in serlog:
                raise xenrt.XRTError("Host serial console is not functional")
            else:
                raise xenrt.XRTFailure("Unexpected output in serial logs")
    
    def postRun(self):
        self.host.execdom0("cp -f {0}.backup {0}".format(self.hvmloaderPath))

class TCXSA121(_TCXSA):
    """Test to verify XSA-121"""
    # Jira TC-27310
    HVM_LOADER = "/usr/groups/xenrt/xsa_test_files/test-hvm64-xsa-121"

    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        step("Install HVM guest")
        self.guest = self.host.createGenericEmptyGuest()
        self.guest.insertToolsCD()
        step("Pin the guest to a specific pcpu")
        cpus = self.host.getCPUCores()
        self.guest.paramSet("VCPUs-params:mask", cpus-1)

        step("Replace HVM Loader")
        self.replaceHvmloader(self.HVM_LOADER)

    def run(self, arglist=None):
        step("Start the guest")
        self.guest.lifecycleOperation("vm-start", timeout=30)

        self.checkHost()
        step("Print Serial Console Logs")
        serlog = string.join(self.host.machine.getConsoleLogHistory(), "\n")
        xenrt.TEC().logverbose(serlog)

        if "All done: No hypervisor stack leaked into guest" in serlog:
            xenrt.TEC().logverbose("Expected output: Found 'All done: No hypervisor stack leaked into guest' in serial log")
        elif "Test failed: Hypervisor stack leaked into guest" in serlog:
            raise xenrt.XRTFailure("XSA not fixed.Found 'Test failed: Hypervisor stack leaked into guest' in logs")
        else:
            #Workaround for CA-159772: Sometimes host serial log is not available for a machine
            #Raise an error in that case.
            if "not found" in serlog or "Enter `^Ec?' for help" in serlog:
                raise xenrt.XRTError("Host serial console is not functional")
            else:
                raise xenrt.XRTFailure("Unexpected output in serial logs")

    def postRun(self):
        self.host.execdom0("cp -f {0}.backup {0}".format(self.hvmloaderPath))

class TCXSA122(TCXSA121):
    """Test to verify XSA-122"""
    # Jira TC-27311

    HVM_LOADER =  "/usr/groups/xenrt/xsa_test_files/test-hvm64-xsa-122"

class TCXSA133(_TCXSA):
    """Test to verify XSA-133"""
    # Jira TC-27014
    
    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        self.guest = self.host.createGenericEmptyGuest()
        self.replaceHvmloader("/usr/groups/xenrt/xsa_test_files/test-hvm64-xsa-133")
        
    def run(self, arglist=None):

        # We can't use start() as this expects a VM to boot and do 'normal' things
        self.guest.lifecycleOperation("vm-start", timeout=30)
        domid = self.guest.getDomid()
        qpid = self.host.xenstoreRead("/local/domain/%u/qemu-pid" % domid)

        starttime = xenrt.util.timenow()
        while True:
            if xenrt.util.timenow() - starttime > 1800:
                raise xenrt.XRTError("Timed out waiting for XSA-133 test")

            qemuRunning = (self.host.execdom0("test -d /proc/%s" % (qpid), retval="code") == 0)
            state = self.guest.getState()

            # Check if we have a successful run
            data = self.host.execdom0("grep qemu-dm-%s /var/log/messages /var/log/daemon.log || true" % (domid))

            if "XSA-133 PoC done - not vulnerable" in data:
                xenrt.TEC().logverbose("Test completed successfully")
                break

            if state == "DOWN" or not qemuRunning:
                raise xenrt.XRTFailure("Host appears vulnerable to XSA-133")

            xenrt.sleep(30)

    def postRun(self):
        self.host.execdom0("cp -f {0}.backup {0}".format(self.hvmloaderPath))

class TCXSA138(_TCXSA):
    """Test to verify XSA-138"""
    # Jira TC-27142
    
    def prepare(self, arglist=None):
        _TCXSA.prepare(self, arglist)
        self.guest = self.host.createGenericEmptyGuest()
        self.guest.insertToolsCD()
        self.replaceHvmloader("/usr/groups/xenrt/xsa_test_files/test-hvm-xsa-138")
        
    def run(self, arglist=None):
        self.guest.lifecycleOperation("vm-start", timeout=30)
        domId = self.guest.getDomid()
        qPid = self.host.xenstoreRead("/local/domain/%u/qemu-pid" % domId)

        startTime = xenrt.util.timenow()
        while True:
            if xenrt.util.timenow() - startTime > 1800:
                raise xenrt.XRTError("Timed out waiting for XSA-138 test")

            qemuRunning = (self.host.execdom0("test -d /proc/%s" % (qPid), retval="code") == 0)
            state = self.guest.getState()

            # Check if we have a successful run
            data = self.host.execdom0("grep qemu-dm-%s /var/log/messages /var/log/daemon.log || true" % (domId))

            if "XSA-138 PoC done - probably not vulnerable" in data and state == "DOWN":
                xenrt.TEC().logverbose("Test completed successfully")
                break

            if not qemuRunning:
                raise xenrt.XRTFailure("Host appears vulnerable to XSA-138")

            xenrt.sleep(30)

    def postRun(self):
        self.host.execdom0("cp -f {0}.backup {0}".format(self.hvmloaderPath))
