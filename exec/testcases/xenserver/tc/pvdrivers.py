#
# XenRT: Test harness for Xen and the XenServer product family
#
# PV driver testcases
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, os.path
from datetime import datetime
import xenrt
from xenrt.lazylog import step
from xenrt.lib.xenserver.signedpackages import SignedXenCenter, SignedWindowsTools

class TC8369(xenrt.TestCase):
    """Verify Windows PV drivers install to a Windows 2008 x64 VM without a test certificate"""

    DISTRO = "ws08sp2-x64"
    ALLOWED_NEW_CERTIFICATES = [
                                "DE28F4A4 FFE5B92F A3C503D1 A349A7F9 962A8212" # Geotrust Global CA (new root cert appears due to MS)
                               ]

    def prepare(self, arglist):
        # Get a host to install on
        self.host = self.getDefaultHost()
        
        self.guest = xenrt.lib.xenserver.guest.createVM(\
            self.host,
            xenrt.randomGuestName(),
            self.DISTRO,
            vifs=xenrt.lib.xenserver.Guest.DEFAULT)
        self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)

        # Record the list of certificates installed on the guest
        # so that we can compare to this after driver install
        self.certsBefore = self.guest.getWindowsCertList()

        # Signtool is required for digital signature verification
        self.guest.xmlrpcUnpackTarball("%s/signtool.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")

    def checkCerts(self):
        """Since Tampa the Windows PV driver installer will automatically
        install test certificates if the drivers are unsigned. This
        subcase checks that no such drivers have been installed (the
        expected behaviour for a RTM release)."""
        certsAfter = self.guest.getWindowsCertList()
        sha1Before = []
        for c in certsAfter:
            sha1Before.append(c[2])

        newCerts = []
        for cert in certsAfter:
            (certno, subject, sha1) = cert
            if not sha1 in sha1Before:
                if sha1 in self.ALLOWED_NEW_CERTIFICATES:
                    xenrt.TEC().logverbose("Found allowed new certificate '%s'" % (cert))
                else:
                    newCerts.append(cert)
                    xenrt.TEC().warning("New certificate '%s' found" % (cert))
        if len(newCerts) > 0:
            raise xenrt.XRTFailure("Certificate(s) installed by PV driver installer")

        # The tools installer can also install test signed drivers - we need to
        # verify that it hasn't done so
        drivers = self.guest.xmlrpcGlobpath("C:\\Program Files\\Citrix\\XenTools\\*\\*.sys")
        if len(drivers) == 0:
            drivers = self.guest.xmlrpcGlobpath("C:\\Program Files (x86)\\Citrix\\XenTools\\*\\*.sys")
        signFailures = []
        for d in drivers:
            try:
                if self.guest.xmlrpcGetArch() == "amd64":
                    stexe = "signtool_x64.exe"
                else:
                    stexe = "signtool_x86.exe"
                data = self.guest.xmlrpcExec("c:\\signtool\\%s verify /kp /v \"%s\"" % (stexe, d), returndata=True)
                if not "Citrix Systems, Inc." in data:
                    xenrt.TEC().logverbose("Didn't find 'Citrix Systems, Inc.' in signtool output - marking as incorrectly signed")
                    signFailures.append(d)
            except:
                signFailures.append(d)

        if len(signFailures) > 0:
            raise xenrt.XRTFailure("Incorrectly signed PV drivers detected", data="Signature issues with: %s" % str(signFailures))

    def checkDrivers(self):
        """Check that the PV drivers can be installed and that the VM
        operates afterwards. This is done without any additional
        certificates so only signed drivers can be successfully
        installed."""
        self.guest.installDrivers()
        self.guest.waitForAgent(180)
        self.guest.reboot()
        self.guest.check()

    def run(self, arglist):
        if self.runSubcase("checkDrivers", (), "Drivers", "Check") == xenrt.RESULT_PASS:
            self.runSubcase("checkCerts", (), "Certs", "Check")

class TC23788(TC8369):
    """Verify Windows PV drivers install to a Windows 7 x86 VM without a test certificate"""

    DISTRO = "win7sp1-x86"

class TestSignedComponent(xenrt.TestCase):
    """ Verify the digital signature of signed XenCenter and Windows drivers/tools"""

    def prepare(self, arglist=None):
        self.args  = self.parseArgsKeyValue(arglist)
        self.guest = self.getGuest(self.args['guest'])
        self.uninstallOnCleanup(self.guest)

        # Signtool is required for digital signature verification of binary
        self.guest.xmlrpcUnpackTarball("%s/signtool.tgz" % (xenrt.TEC().lookup("TEST_TARBALL_BASE")), "c:\\")

    def run(self, arglist=None):

        # Get the instance of the components we are testing
        testObjects=[SignedXenCenter(),SignedWindowsTools()]
        for testObj in testObjects:
            testComponent = testObj.description()
            self.declareTestcase("TestSignedComponent",testComponent)
            self.runSubcase("doTest", (testObj,testComponent), "TestSignedComponent",testComponent)

    def doTest(self,testObj,fileToVerify):

        # Fetch the file from the package 
        exe=testObj.fetchFile()
        self.guest.xmlrpcSendFile(exe,fileToVerify)

        # Verify the digital signature of the binary
        testObj.verifySignature(self.guest,fileToVerify)

        # Get the Certificate expiry date of signed binary
        expiryDate=testObj.getCertExpiryDate(self.guest,fileToVerify)

        # Set a new guest date so as to past the cert expiry date. We add a year to it
        expiryYear=datetime.strptime(expiryDate,"%m-%d-%y").strftime("%Y")
        newDate=datetime.strptime(expiryDate,"%m-%d-%y").replace(year=int(expiryYear)+1)
        testObj.changeGuestDate(self.guest,newDate)

        # If the binary is digitally signed with valid certificate we should be able to install
        testObj.installPackages(self.guest)

class _LinuxKernelUpdate(xenrt.TestCase):
    """Installing PV tools to a VM replaces the kernel with a Citrix kernel"""

    ARCH = "x86-32"
    DISTRO = None
    REPLACE = True

    def prepare(self, arglist):
        if not self.DISTRO:
            raise xenrt.XRTError("No DISTRO defined for testcase")
        
        self.host = self.getDefaultHost()

        # Install a VM without automatically installing the tools
        self.guest = xenrt.lib.xenserver.guest.createVM(\
            self.host,
            xenrt.randomGuestName(),
            distro=self.DISTRO,
            arch=self.ARCH,
            vifs=xenrt.lib.xenserver.Guest.DEFAULT,
            notools=True)
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist):

        # Check the kernel version before the tools are installed
        oldkver = self.guest.execguest("uname -r").strip()
        xenrt.TEC().comment("Old kernel version %s" % (oldkver))

        # Install the tools
        self.guest.installTools(reboot=True)

        # Check the kernel version again and verified it has changed
        newkver = self.guest.execguest("uname -r").strip()
        if self.REPLACE and newkver == oldkver:
            raise xenrt.XRTFailure("After installing the tools/kernel a %s "
                                   "%s VM has the same kernel as before: %s" %
                                   (self.DISTRO, self.ARCH, oldkver))
        elif (not self.REPLACE) and newkver != oldkver:
            raise xenrt.XRTFailure("After installing the tools a %s %s VM has "
                                   "a %s kernel vs a %s before" %
                                   (self.DISTRO, self.ARCH, newkver, oldkver))

        xenrt.TEC().comment("New kernel version %s" % (newkver))

class _NoLinuxKernelUpdate(_LinuxKernelUpdate):
    """Installing PV tools to a VM doesn't replace the kernel with a Citrix kernel"""
    REPLACE = False


class TC9180(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 4.5 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel45"
    
class TC9181(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 4.6 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel46"
    
class TC9182(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 4.7 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel47"

class TC9577(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 4.8 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel48"
    
class TC9183(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 4.5 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos45"
    
class TC9184(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 4.6 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos46"
    
class TC9185(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 4.7 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos47"

class TC9578(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 4.8 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos48"

class TC9186(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.0 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel5"

class TC9187(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.1 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel51"

class TC9188(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.2 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel52"

class TC9189(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.3 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel53"

class TC9190(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.0 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel5"
    ARCH = "x86-64"

class TC9191(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.1 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel51"
    ARCH = "x86-64"

class TC9192(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.2 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel52"
    ARCH = "x86-64"

class TC9193(_LinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.3 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "rhel53"
    ARCH = "x86-64"

class TC9194(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.0 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos5"

class TC9195(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.1 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos51"

class TC9196(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.2 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos52"

class TC9197(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.3 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos53"

class TC9198(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.0 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos5"
    ARCH = "x86-64"

class TC9199(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.1 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos51"
    ARCH = "x86-64"

class TC9200(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.2 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos52"
    ARCH = "x86-64"

class TC9201(_LinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.3 x86-64 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "centos53"
    ARCH = "x86-64"

class TC9202(_LinuxKernelUpdate):
    """Installing PV tools to a SLES9 SP4 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "sles94"

class TC9203(_LinuxKernelUpdate):
    """Installing PV tools to a Debian Etch VM replaces the kernel with a Citrix kernel"""
    DISTRO = "etch"

class TC9204(_LinuxKernelUpdate):
    """Installing PV tools to a Debian Lenny 5.0 VM replaces the kernel with a Citrix kernel"""
    DISTRO = "debian50"


class TC11035(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.0 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel5"

class TC11037(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.1 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel51"

class TC11039(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.2 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel52"

class TC11041(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.3 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel53"

class TC11043(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.4 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel54"

class TC12569(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.5 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel55"

class TC11036(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.0 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel5"
    ARCH = "x86-64"

class TC11038(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.1 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel51"
    ARCH = "x86-64"

class TC11040(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.2 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel52"
    ARCH = "x86-64"

class TC11042(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.3 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel53"
    ARCH = "x86-64"

class TC11044(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.4 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel54"
    ARCH = "x86-64"

class TC12570(_NoLinuxKernelUpdate):
    """Installing PV tools to a RHEL 5.5 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "rhel55"
    ARCH = "x86-64"

class TC11045(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.0 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos5"

class TC11047(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.1 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos51"

class TC11049(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.2 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos52"

class TC11051(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.3 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos53"

class TC11053(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.4 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos54"

class TC11046(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.0 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos5"
    ARCH = "x86-64"

class TC11048(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.1 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos51"
    ARCH = "x86-64"

class TC11050(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.2 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos52"
    ARCH = "x86-64"

class TC11052(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.3 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos53"
    ARCH = "x86-64"

class TC11054(_NoLinuxKernelUpdate):
    """Installing PV tools to a CentOS 5.4 x86-64 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "centos54"
    ARCH = "x86-64"

class TC11055(_NoLinuxKernelUpdate):
    """Installing PV tools to a OEL 5.3 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "oel53"

class TC11057(_NoLinuxKernelUpdate):
    """Installing PV tools to a OEL 5.4 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "oel54"

class TC11056(_NoLinuxKernelUpdate):
    """Installing PV tools to a OEL 5.3 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "oel53"
    ARCH = "x86-64"

class TC11058(_NoLinuxKernelUpdate):
    """Installing PV tools to a OEL 5.4 VM doesn't replace the kernel with a Citrix kernel"""
    DISTRO = "oel54"
    ARCH = "x86-64"


class _VerifyNic(xenrt.TestCase):
    """ Verify a NIC field after updating from emulated driver to PV driver on Windows"""

    distro = None
    vcpus = None
    memory = None

    netName = None
    fields = None
    include = True

    cmdPrefix = 'netsh interface ip'
    
    # Required instance variable
    getcmd = None

    def setCmd(self,conf):
        pass

    def getConfig(self):
        if self.getcmd is None:
            raise xenrt.XRTError("getcmd is a required instance variable")
        cmd = " ".join([self.cmdPrefix, "show", self.getcmd])
        netshconfig = self.guest.getWindowsNetshConfig(cmd)
        ipconfig = self.guest.getWindowsIPConfigData()
        config = {}
        for net, conf in netshconfig.iteritems():
            xconf = ipconfig.get(net)
            if xconf:
                config[net] = conf
                config[net]['ipconfig'] = xconf
        xenrt.TEC().logverbose("""Get configuration with command "%s":
%s""" % (cmd, config))
        return config

    def setConfig(self, setcmd):
        for netName, cmddict in setcmd.iteritems():
            for cmd,args in cmddict.iteritems():
                cmd = " ".join([self.cmdPrefix, 'set', cmd, 'name="%s"' % netName, args])
                self.guest.xmlrpcExec(cmd)
                xenrt.TEC().logverbose('Set configuration with command "%s"' % cmd)

    def selectFields(self, config):
        xenrt.TEC().logverbose("""Select fields from original configuration:
%s""" % config)
        if self.netName is not None:
            config = dict(filter(lambda(name, conf): re.search(self.netName, name), config.iteritems()))
        if self.fields is not None:
            config = dict(map(lambda(net, conf): (net, dict(filter(lambda(field,cont): (self.include and field in self.fields or not self.include and field not in self.fields), conf.iteritems()))), config.iteritems()))
        xenrt.TEC().logverbose("""The result of selection:
%s""" % config)
        return config

    def configDiff(self, confx, confy):
        confx = dict(map(lambda(a,b):(b['ipconfig']['Physical Address'], b), confx.iteritems()))
        confy = dict(map(lambda(a,b):(b['ipconfig']['Physical Address'], b), confy.iteritems()))
        confx = self.selectFields(confx)
        confy = self.selectFields(confy)
        diff = {}
        for net in confx:
            yfields = confy.pop(net, None)
            if yfields is None:
                diff[net] = { 'OLD': confx[net], 'NEW': None }
            else:
                for field in confx[net]:
                    yfield = yfields.pop(field, None)
                    if yfield != confx[net][field]:
                        if not diff.has_key(net):
                            diff[net] = {}
                        diff[net][field] = { 'OLD': confx[net][field], 'NEW': yfield }
                for field in yfields:
                    if not diff.has_key(net):
                        diff[net] = {}
                    diff[net][field] = { 'OLD' : None, 'NEW': yfields[field] }
        for net in confy:
            diff[net] = { 'OLD': None, 'NEW': confy[net] }
        return diff

    def verify(self, oldConfig, newConfig):
        xenrt.TEC().logverbose("""Verfiy the NIC settings:
Old config: %s
New config: %s
""" % (oldConfig, newConfig))
        diff = self.configDiff(oldConfig, newConfig)
        if len(diff) == 0:
            xenrt.TEC().logverbose("NIC settings are preserved after PVdrivers installation")
        else:
            fieldset = set([])
            for net in diff:
                fieldset = set.union(fieldset, set(diff[net].keys()))
            raise xenrt.XRTFailure("NIC setting are not preserved after PVdrivers installation. Problematic fields: %s" % ", ".join(fieldset), data=diff) 

    def prepare(self, arglist):
        argdict = xenrt.util.strlistToDict(arglist)
        if argdict.has_key('guest'):
            self.host = self.getDefaultHost()
            guest = self.host.getGuest(argdict['guest'])
            if not guest.windows:
                raise xenrt.XRTError("Windows only test")
            guest.enlightenedDrivers = False
            if guest.getState() == 'UP':
                guest.shutdown(force=True)
            self.guest = guest.cloneVM()
            self.uninstallOnCleanup(self.guest)
            self.guest.start()
            try:
                self.guest.checkPVDevices()
            except xenrt.XRTFailure:
                pass
            else:
                raise xenrt.XRTError("PV driver already installed in guest template")
        else:
            if argdict.has_key('distro'):
                self.distro = argdict['distro']
            if argdict.has_key('vcpus'):
                self.vcpus = int(argdict['vcpus'])
            if argdict.has_key('memory'):
                self.memory = int(argdict['memory'])
            self.host = self.getDefaultHost()
            self.guest = self.host.createGenericWindowsGuest(drivers=False,
                                                             distro=self.distro,
                                                             vcpus=self.vcpus,
                                                             memory=self.memory)
            self.uninstallOnCleanup(self.guest)
        self.getLogsFrom(self.guest)
        
    def run(self, arglist):
        if self.guest.getState() == 'DOWN':
            self.guest.start()
        oldfield = self.getConfig()
        setcmd = self.setCmd(oldfield)
        if setcmd is not None:
            self.setConfig(setcmd)
            oldfield = self.getConfig()
        try:
            self.guest.installDrivers(extrareboot=True)
        except xenrt.XRTFailure, e:
            if "Domain running but not reachable by" in e.reason:
                # See if the VM got a link-local address
                try:
                    ip = self.guest.paramGet("networks", "0/ip")
                except:
                    ip = None
                if ip and re.match("169\.254\..*", ip):
                    raise xenrt.XRTFailure(\
                        "VM gave itself a link-local address.")
            raise
        newfield = self.getConfig()
        extraRebootCount=2
        while extraRebootCount:
            try:
                extraRebootCount-=1
                self.verify(oldfield, newfield)               
                break
            except xenrt.XRTFailure, e:
                self.guest.reboot()
        
        if not extraRebootCount :
            self.verify(oldfield, newfield)


class TC9276(_VerifyNic):
    """Verify default DNS settings are preserved after PV drivers installation on a Windows machine"""
    getcmd = "dns"
    fields = ['DNS servers configured through DHCP', 'Statically Configured DNS Servers']
    
class TC9277(_VerifyNic):
    """Verfiy default WINS settings are preserved after PV drivers installation on a windows machine"""
    getcmd = "wins"
    fields = ['WINS servers configured through DHCP', 'Statically Configured WINS Servers']

class TC9278(_VerifyNic):
    """Verify default DNS registration settings are preserved after PV drivers installation on a windows machine"""
    getcmd = "dns"
    fields = ['Register with which suffix']

class TC9279(_VerifyNic):
    """Verify default DHCP settings are preserved after PV drivers installation on a windows machine"""
    getcmd = "addr"
    fields = ['DHCP enabled']

class TC9280(_VerifyNic):
    """Verify default IP address settings are preserved after PV drivers installation on a windows machine"""
    getcmd = "addr"
    fields = ['DHCP enabled', 'IP Address', 'SubnetMask', 'Subnet Prefix', 'Default Gateway', 'Gateway Metric']

class TC9281(_VerifyNic):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a windows machine"""
    getcmd = "config"
    include = False
    fields = ['InterfaceMetric', 'ipconfig']

    def setCmd(self, conf):
        nic1 = conf.keys()[0]
        ipconfig = conf[nic1]['ipconfig']
        if ipconfig.has_key('IPv4 Address'):
            ipaddress = ipconfig['IPv4 Address']
            gwmetricstr = (conf[nic1].has_key('Gateway Metric') and (" gwmetric=%d" % random.randint(1,255)) or "")
        elif ipconfig.has_key('IP Address'):
            ipaddress = ipconfig['IP Address']
            gwmetricstr = " gwmetric=25"
        else:
            raise xenrt.XRTError("Could not locate IP address in config",
                                 str(ipconfig))
        cmddict = {
            "dns" : "source=static addr=%s" % "169.254.0.3" + (conf[nic1].get('Register with which suffix') and " register=both" or ""),
            "wins": "source=static addr=%s" % "169.254.0.2",
            "addr": "source=static addr=%s mask=%s gateway=%s" % (re.match('(\d+\.\d+\.\d+\.\d+)', ipaddress).groups()[0], 
                                                                  ipconfig['Subnet Mask'],
                                                                  re.search("\d+\.\d+.\d+\.\d+", ipconfig['Default Gateway']).group(0)) + gwmetricstr
            }
        
        return {nic1: cmddict}

class TC10758(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows 2008 R2 VM"""
    
    distro = "ws08r2-x64"

class TC12571(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows 2008 R2 SP1 VM"""
    
    distro = "ws08r2sp1-x64"

class TC10760(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows 7 x86 VM"""
    
    distro = "win7-x86"

class TC10761(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows 7 x64 VM"""
    
    distro = "win7-x64"

class TC12572(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows 7 SP1 x86 VM"""
    
    distro = "win7sp1-x86"

class TC12573(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows 7 SP1 x64 VM"""
    
    distro = "win7sp1-x64"

class TC10762(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows Vista EE SP2 VM"""
    
    distro = "vistaeesp2"

class TC10763(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows XP SP3 VM"""
    
    distro = "winxpsp3"

class TC10764(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows Server 2003 EE SP2 VM"""
    
    distro = "w2k3eesp2"

class TC10765(TC9281):
    """Verify a customized NIC settings set is preserved after PV drivers installation on a Windows 2000 SP4 VM"""
    
    distro = "w2kassp4"
    
class _Xstest(xenrt.TestCase):
    """Run xstest and friends from XenRT"""

    DISTRO = None
    ARCH = None

    TAR = "xe-phase-1/pvdrivers-build-crosssigned.tar.gz"
    TAR2 = "pvdrivers-build-crosssigned.tar.gz"

    PATH32= { "src": "windows/build/i386",
              "dst": "C:\\Program Files\\Citrix\\XenTools" }
    PATH64= { "src": "windows/build/amd64",
              "dst": "C:\\Program Files (x86)\\Citrix\\XenTools" }

    CONF32 = { "xstest":
               { "exec": "xstest.exe",
                 "srcpath": PATH32["src"],
                 "dstpath": PATH32["dst"],
                 "timeout": 600 },
               "xs2test":
               { "exec": "xs2test.exe",
                 "srcpath": PATH32["src"],
                 "dstpath": PATH32["dst"],
                 "timeout": 600 },
               "xstest_dyn":
               { "exec": "xstest_dyn.exe",
                 "srcpath": PATH32["src"],
                 "require": "\\".join([PATH32["dst"], "xsutil.dll"]),
                 "timeout": 60 } }
    CONF64 = { "xstest":
               { "exec": "xstest.exe",
                 "srcpath": PATH64["src"], 
                 "dstpath": PATH64["dst"],
                 "timeout": 600 },
               "xs2test":
               { "exec": "xs2test.exe",
                 "srcpath": PATH64["src"], 
                 "dstpath": PATH64["dst"],
                 "timeout": 600 },
               "xstest_dyn":
               { "exec": "xstest_dyn.exe",
                 "srcpath": PATH64["src"],
                 "require": "\\".join([PATH64["dst"], "xsutil.dll"]),
                 "timeout": 60 },
               "xs2test_32":
               { "exec": "xs2test.exe",
                 "srcpath": PATH32["src"], 
                 "require": "\\".join([PATH64["dst"], "xs2_32.dll"]),
                 "prepare": "copy /Y xs2_32.dll xs2.dll",
                 "timeout": 600 } }

    def prepare(self, arglist):

        args = xenrt.util.strlistToDict(arglist)
        self.host = self.getDefaultHost()

        distro_spec = args.get("distro") or self.DISTRO
        if distro_spec:
            if self.ARCH and (self.ARCH.endswith("64") != distro_spec.endswith("64")):
                raise xenrt.XRTError("The distro argument (%s) specifies an different "
                                     "arch from the testcase's default (%s)."
                                     % (distro_spec, self.ARCH))
            if "wv".find(distro_spec[0]) < 0:
                raise xenrt.XRTError("Guest distribution: %s is not Windows" % distro_spec)
            self.DISTRO = distro_spec
        elif self.ARCH:
            distro_key = "GENERIC_WINDOWS_OS" + (self.ARCH.endswith("64") and "_64" or "")
            self.DISTRO = self.host.lookup(distro_key)
        else:
            raise xenrt.XRTFailure("At least one of distribution and archetecture must be specified")

        self.conf = self.DISTRO.endswith("64") and self.CONF64 or self.CONF32
         
        tar_ball = xenrt.TEC().getFile(self.TAR, self.TAR2)
        if tar_ball is None:
            raise xenrt.XRTError("No pvdrivers build tarball found at %s or %s"
                                 % (self.TAR, self.TAR2))
        self.temp_dir = xenrt.TEC().tempDir()
        xenrt.command("tar -C %s -xvzf %s" % (self.temp_dir, tar_ball))
        
        self.guest = self.host.createGenericWindowsGuest(distro=self.DISTRO,
                                                         arch = self.ARCH)
        self.uninstallOnCleanup(self.guest)

        # For quick test only
        # self.guest = self.host.getGuest(self.DISTRO)

    def runtest(self, sc):
        conf = self.conf[sc]
        if not conf.has_key("dstpath"):
            conf["dstpath"] = self.guest.xmlrpcTempDir()
        self.guest.xmlrpcSendFile("/".join([self.temp_dir, conf["srcpath"], conf["exec"]]),
                                  "\\".join([conf["dstpath"], conf["exec"]]))
        if conf.has_key("require"):
            self.guest.xmlrpcExec("copy \"%s\" \"%s\"" % (conf["require"], conf["dstpath"]))
        # It could be a problem if the working path and dst path are not on the same driver
        chdir = "cd \"%s\"" % conf["dstpath"]
        steps = [chdir, conf.get("prepare"), conf.get("exec"), conf.get("postrun")]
        cmd = "\n".join(filter(None, steps))
        self.guest.xmlrpcExec(cmd, timeout=conf["timeout"])

    def run(self, arglist):
        for sc in self.conf:
            self.runSubcase("runtest", sc, "xstest", sc)

class TC9362(_Xstest):
    """Run xstest and friends on a 32bit Windows guest from XenRT"""
    ARCH="x86-32"

class TC9363(_Xstest):
    """ Run xstest and friends on a 64bit Windows guest from XenRT"""
    ARCH="x86-64"

class TC12157(xenrt.TestCase):

    def setMTU(self, mtu):
        self.guest.setNetworkViaXenstore("tcpip", "MTU", "dword", str(mtu))

    def checkMTU(self, mtu):
        result = self.guest.xmlrpcExec("netsh int ip show sub",
                                       returndata=True)
        result = map(lambda x:filter(None, x.split('  ')),
                     result.strip().splitlines()[4:])
        mtuvalue = None
        for r in result:
            if r[4].startswith("Local Area Connection"):
                mtuvalue = int(r[0])
                break
        if not mtuvalue:
            raise xenrt.XRTError("Failed to find MTU value")
        if mtu != mtuvalue:
            raise xenrt.XRTFailure("Wrong MTU value, expect %d, found %d."
                                   % (mtu, mtuvalue))
    def setTCPNameServer(self, srvs):
        self.guest.setNetworkViaXenstore("tcpip", "NameServer", "string", ",".join(srvs))
        
    def checkTCPNameServer(self, srvs):
        ipconf = self.guest.getWindowsIPConfigData()[self.drvnet]
        srvs_obs = ipconf['DNS Servers'].strip().split()
        if set(srvs_obs) != set(srvs):
            raise xenrt.XRTFailure("Wrong TCP nameservers, expect %s, found %s"
                                   % (srvs, srvs_obs))
        
    def setNbtNameServer(self, srv):
        self.guest.setNetworkViaXenstore("nbt", "NameServer", "string", srv)

    def checkNbtNameServer(self, srv):
        nbtuuid = self.guest.winRegLookup('HKLM',
                                          'SYSTEM\\CurrentControlSet\\Control\\Class\\{4D36E972-E325-11CE-BFC1-08002BE10318}\\%04d'%self.drvid,
                                          'NetCfgInstanceId')
        for controlset in ['ControlSet001', 'ControlSet002', 'CurrentControlSet']:
            ns = self.guest.winRegLookup('HKLM',
                                         'SYSTEM\\%s\\Services\\NetBT\\Parameters\\Interfaces\\Tcpip_%s' % (controlset, nbtuuid),
                                         'Nameserver')
            if ns != srv:
                raise xenrt.XRTFailure("Wrong Nbt nameserver, expect %s, found %s"
                                       % (srv, ns))
            
    def setEnableDhcp(self):
        self.guest.setNetworkViaXenstore("tcpip", "EnableDhcp", "dword", "1")

    def checkEnableDhcp(self):
        ipconf = self.guest.getWindowsIPConfigData()[self.drvnet]
        if ipconf['DHCP Enabled'] != 'Yes':
            raise xenrt.XRTFailure("Wrong DHCP setting, expect %s, found %s"
                                   % ('Yes', ipconf['DHCP Enabled']))
        
    def setStaticIP(self, gateway, ip, submask):
        self.guest.setNetworkViaXenstore("tcpip", "EnableDhcp", "dword", "0")
        self.guest.setNetworkViaXenstore("tcpip", "DefaultGateway", "multi_sz",
                                         [self.ipconf[self.drvnet]['Default Gateway'],
                                         gateway])
        self.guest.setNetworkViaXenstore("tcpip", "IPAddress", "multi_sz",
                                         [self.ipconf[self.drvnet]['IPv4 Address'].split('(')[0],
                                         ip])
        self.guest.setNetworkViaXenstore("tcpip", "SubnetMask", "multi_sz",
                                         [self.ipconf[self.drvnet]["Subnet Mask"], submask])


    def checkStaticIP(self, gateway, ip, submask):
        ipconf = self.guest.getWindowsIPConfigData()[self.drvnet]
        if not gateway in ipconf['Default Gateway'].split():
            raise xenrt.XRTFailure("Wrong gateway setting, expect %s, found %s"
                                   % (gateway, ipconf['Default Gateway']))
        if ip != ipconf['IPv4 Address'].split('(')[0]:
            raise xenrt.XRTFailure("Wrong ip address, expect %s, found %s"
                                   % (ip, ipconf['IPv4 Address']))
        if submask != ipconf['Subnet Mask']:
            raise xenrt.XRTFailure("Wrong subnet mask, expect %s, found %s"
                                   % (submask, ipconf['Subnet Mask']))
            
    def setXenserverConf(self, tcpcs, udpcs, ls, csblank):
        self.guest.setNetworkViaXenstore("xenserver",
                                         "*TCPChecksumOffloadIPv4",
                                         "dword", str(tcpcs))
        self.guest.setNetworkViaXenstore("xenserver",
                                         "*UDPChecksumOffloadIPv4",
                                         "dword", str(udpcs))
        self.guest.setNetworkViaXenstore("xenserver",
                                         "*LSOv1IPv4",
                                         "dword", str(ls))
        self.guest.setNetworkViaXenstore("xenserver",
                                         "AllowCsumBlank",
                                         "dword", str(csblank))
        
    def testXenserverConf(self, name, value):
        for controlset in ['ControlSet001', 'ControlSet002',
                           'CurrentControlSet']:
            try:  
                obs = self.guest.winRegLookup('HKLM',
                                              'SYSTEM\\%s\\Control\\Class\\{4D36E972-E325-11CE-BFC1-08002BE10318}\\%04d'
                                              % (controlset, self.drvid),
                                              name)
            except Exception, e:
                obs = e
            if obs != value:
                return obs

        return True
    
    
    def checkXenserverConf(self, tcpcs, udpcs, ls, csblank):

        for name,value in [('*TCPChecksumOffloadIPv4', tcpcs),
                           ('*UDPChecksumOffloadIPv4', udpcs),
                           ('*LSOv1IPv4', ls),
                           ("AllowCsumBlank", csblank)]:
            result = self.testXenserverConf(name, value)
            if result is not True:
                raise xenrt.XRTFailure("Wrong %s in registry, expect %s, found %s"
                                       % (name, value, result))

    def resetAll(self, g, x):
        self.guest.paramClear("xenstore-data")

    def checkReset(self, gateway, xenserverconf):
        ipconf = self.guest.getWindowsIPConfigData()[self.drvnet]
        if gateway not in ipconf['Default Gateway'].split():
            raise xenrt.XRTFailure("Previous default gateway setting should stay until being cleaned up explicitly but it's not")
        # xenserver conf should stay as well, recheck
        self.checkXenserverConf(*xenserverconf)

    def removeRest(self, g, x):
        self.guest.setNetworkViaXenstore("tcpip", "DefaultGateway", "remove", "")
        for name in ["*TCPChecksumOffloadIPv4", "*UDPChecksumOffloadIPv4", "*LSOv1IPv4", "AllowCsumBlank"]:
            self.guest.setNetworkViaXenstore("xenserver", name, "remove", "")

    def checkRemove(self,gateway, xenserverconf):
        tcpcs, udpcs, ls, csblank = xenserverconf
        for name,value in [('*TCPChecksumOffloadIPv4', tcpcs),
                           ('*UDPChecksumOffloadIPv4', udpcs),
                           ('*LSOv1IPv4', ls),
                           ("AllowCsumBlank", csblank)]:
            result = self.testXenserverConf(name, value)
            if not isinstance(result, Exception):
                raise xenrt.XRTFailure("Xenserver config should go away after explicit removing but we see %s -> %s"
                                       % (name, (result is True) and value or result))
        ipconf = self.guest.getWindowsIPConfigData()[self.drvnet]
        if gateway in ipconf['Default Gateway'].split():
            raise xenrt.XRTFailure("Previous default gateway setting should go away after explicit removing but it's not")
        
    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        guest = self.host.getGuest(self.host.listGuests()[0])
        if not guest.windows: 
            raise xenrt.XRTError("Windows only test")
        
        guest.enlightenedDrivers = False
        guest.goState('DOWN')
        self.guest = guest.cloneVM()
        self.uninstallOnCleanup(self.guest)
        self.guest.start()
        self.guest.installDrivers()
        
        self.drvnet = None
        self.ipconf = self.guest.getWindowsIPConfigData()
        
        for n in self.ipconf:
            if self.ipconf[n].has_key('Description') and "Citrix PV" in self.ipconf[n]['Description']:
                self.drvnet = n
                self.drvid = self.guest.getVifOffloadSettings(0).getRegistryId()
                break
        
        if not self.drvnet:
            raise xenrt.XRTException("Didn't not find the network name of PV by searching its name")
        
    def runCase(self, confs):
        extrareboot = False
        for conf in confs:
            value, setter, checker, reboot = conf
            setter(*value)
            extrareboot = extrareboot or reboot
        if extrareboot:
            try:
                self.guest.reboot()
            except:
                pass
        self.guest.reboot()
        for value, setter, checker, reboot in confs:
            checker(*value)

    def run(self, arglist=[]):

        fakegateway = '202.202.202.202'
        xenserverconf = (2,2,0,0)

        cases = [
            ("MTU", [ ((1432,), self.setMTU, self.checkMTU, True) ]),
            ("DNS", [ ((['1.2.3.4', '5.6.7.8'],),
                       self.setTCPNameServer, self.checkTCPNameServer, False),
                      (('9.9.9.9',),
                       self.setNbtNameServer, self.checkNbtNameServer, False)]),
            ("StaticIP", [ ((fakegateway, '200.200.200.200', '255.0.0.0'),
                            self.setStaticIP, self.checkStaticIP, True) ]),
            ("XenServer", [ (xenserverconf, self.setXenserverConf, self.checkXenserverConf, False) ]),
            ("DHCP", [ ((), self.setEnableDhcp, self.checkEnableDhcp, False)]),
            ("Reset", [ ((fakegateway, xenserverconf), self.resetAll, self.checkReset, False) ]),
            ("Remove", [ ((fakegateway, xenserverconf), self.removeRest, self.checkRemove, False) ])
            ]

        fails = []
        for name, confs in cases:
            res = self.runSubcase("runCase", (confs,),
                                  "XenStore-VMdata", name)
            if res != xenrt.RESULT_PASS:
                fails.append(res)

        if len(fails) == 0:
            xenrt.TEC().logverbose("All subcases passed")
        else:
            raise xenrt.XRTFailure("sub testcases failed/skipped/error: %s" % fails)

class CA90861Frequency(xenrt.TestCase):

    def run(self, arglist=None):

        # Set defaults
        distro = "ws08r2sp1-x64"
        vcpus = 2
        memory = 4096
        iterations = 100
        if arglist:
            args = xenrt.util.strlistToDict(arglist)
            if args.has_key("distro"):
                distro = args["distro"]
            if args.has_key("vcpus"):
                vcpus = int(args["vcpus"])
            if args.has_key("memory"):
                memory = int(args["memory"])
            if args.has_key("iterations"):
                iterations = int(args["iterations"])

        host = self.getDefaultHost()

        guest = xenrt.lib.xenserver.guest.createVM(\
            host,
            xenrt.randomGuestName(),
            distro,
            vifs=xenrt.lib.xenserver.Guest.DEFAULT,
            vcpus=vcpus,
            memory=memory)

        guest.installDrivers()
        guest.shutdown()

        success = 0
        for i in range(iterations):
            try:
                guest.lifecycleOperation("vm-start")

                # Now see what IP we get
                foundIP = False
                linkLocalCount = 0
                startTime = xenrt.util.timenow()
                while not foundIP:
                    vifs = guest.getVIFs()
                    dev = vifs.keys()[0]
                    _, ip, _ = vifs[dev]
                    # Did we get an IP at all?
                    if not ip:
                        # no - check again in 10 seconds time
                        if (xenrt.util.timenow() - startTime) > (20 * 60):
                            raise xenrt.XRTFailure("VM didn't boot after 20 minutes")
                        time.sleep(10)
                        continue

                    # We've got an IP - was it a link local?
                    if re.match("169\.254\..*", ip):
                        linkLocalCount += 1
                        if linkLocalCount < 6:
                            # The link local might be transient, we'll only fail if we've seen it 6 times
                            continue
                        else:
                            raise xenrt.XRTFailure("VM gave itself a link-local address.")
                    
                    # Not a link local, so this was a successful boot
                    foundIP = True
                success += 1
                guest.shutdown()
            except:
                traceback.print_exc(file=sys.stderr)
                guest.shutdown(force=True)

            xenrt.TEC().logverbose("Iteration %d complete, success count = %d" % (i, success))

        xenrt.TEC().logverbose("%d/%d iterations completed successfully" % (success, iterations))
        if success < iterations:
            raise xenrt.XRTFailure("VM failed to boot successfully at least once")

class TCToolsMissingUninstall(xenrt.TestCase):
    """Test for SCTX-1634. Verify upgrade of XenTools from XS 6.0 to XS 6.2 is successfull"""
    #TC-23775
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.getGuest("VMWin2k8")
        self.guest.start()

    def run(self, arglist=None):
        step("Remove uninstaller file")
        self.guest.xmlrpcRemoveFile("C:\\Program files\\citrix\\xentools\\uninstaller.exe")

        step("Install 6.2 PV tools")
        self.guest.installDrivers()
        self.guest.waitForAgent(60)
        
        if self.guest.pvDriversUpToDate():
            xenrt.TEC().logverbose("Tools are upto date")
        else:
            raise xenrt.XRTFailure("Guest tools are out of date")
            
class TCToolsVBscriptEngineOff(xenrt.TestCase):
    """Test for SCTX-1650. Verify upgrade of XenTools from XS 6.0 to XS 6.1 is successfull when vbscript engine is not available"""
    #TC-27017
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.getGuest("VMWin2k8")
        self.guest.start()

    def run(self, arglist=None):
        step("Disable vbscript Engine")
        
        self.guest.xmlrpcExec("cd C:\\Windows\\System32")
        self.guest.xmlrpcExec("takeown /f C:\\Windows\\System32\\vbscript.dll")
        self.guest.xmlrpcExec("echo y| cacls C:\\Windows\System32\\vbscript.dll /G administrator:F")
        self.guest.xmlrpcExec("rename vbscript.dll vbscript1.dll")
                 
        step("Install latest PV tools")
        self.guest.installDrivers()
        self.guest.waitForAgent(60)
        
        if self.guest.pvDriversUpToDate():
            xenrt.TEC().logverbose("Tools are upto date")
        else:
            raise xenrt.XRTFailure("Guest tools are out of date")
            
class TCSysrepAfterToolsUpgrade(xenrt.TestCase):
    """Test for SCTX-1906. verifies that after upgrade of XenTools from XS 6.0 to XS 6.2, Sysrep.exe runs successfully"""
    #TC-27018
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.getGuest("VMWin2k8")
        self.guest.start()
        
        step("Install latest PV tools")
        self.guest.installDrivers()
        self.guest.waitForAgent(60)
        
        if self.guest.pvDriversUpToDate():
            xenrt.TEC().logverbose("Tools are upto date")
        else:
            raise xenrt.XRTFailure("Guest tools are out of date")


    def run(self, arglist=None):
        step("Check whether Sysprep gets installed")
        if self.guest.sysPrepOOBE():
            xenrt.TEC().logverbose("Sysprep is installed successfully")
        else:
            raise xenrt.XRTFailure("Sysprep is not installed")
            
class TCToolsIPv6Disabled(xenrt.TestCase):
    """Test for SCTX-1919. Verify upgrade of XenTools from XS 6.0 to XS 6.1 is successfull when IPv6 is disabled"""
    #TC-27019
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.getGuest("VMWin2k8")
        self.guest.start()

    def run(self, arglist=None):
        step("Disable IPv6 Settings")
        self.guest.disableIPv6()
      
        step("Install latest PV tools")
        self.guest.installDrivers()
        self.guest.waitForAgent(60)
        
        if self.guest.pvDriversUpToDate():
            xenrt.TEC().logverbose("Tools are upto date")
        else:
            raise xenrt.XRTFailure("Guest tools are out of date")

class TCBootStartDriverUpgrade(xenrt.TestCase):
    """Test for CA-158777 upgrade issue with boot start driver"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        distro = "win7sp1-x86"
        startDrivers = xenrt.TEC().lookup("START_DRIVERS", "/usr/groups/xenrt/pvtools/esperado.tgz")
        if arglist:
            args = xenrt.util.strlistToDict(arglist)
            if args.has_key("distro"):
                distro = args["distro"]
            elif args.has_key("startdrivers"):
                startDrivers = args["startdrivers"]

        self.guest = self.host.createGenericWindowsGuest(distro=distro, drivers=False)

        # Install the Esperado PV drivers
        self.guest.installDrivers(source=startDrivers, expectUpToDate=False)

        # Make xenvif boot start
        self.guest.setDriversBootStart()

    def run(self, arglist=None):
        # Attempt to upgrade the PV drivers
        self.guest.installDrivers()

class TCPrepareDriverUpgrade(xenrt.TestCase):
    """Utility test which prepares a clone of a template VM with a specified set of tools"""

    def run(self, arglist):
        args = xenrt.util.strlistToDict(arglist)
        template = args["template"]
        tag = args["tag"]
        hotfix = args["hotfix"]

        host = self.getDefaultHost()

        # Get the hotfix file
        hotfixFile = xenrt.TEC().getFile(xenrt.TEC().config.getHotfix(hotfix, None))

        # Extract the tools ISO from the hotfix
        workdir = xenrt.TempDirectory()
        patchDir = host.unpackPatch(hotfixFile)
        toolsIso = host.execdom0("find %s -name \"xs-tools*.iso\"" % patchDir).strip()
        sftp = host.sftpClient()
        localToolsIso = "%s/%s.iso" % (workdir.path(), tag)
        sftp.copyFrom(toolsIso, localToolsIso)
        sftp.close()
        host.execdom0("rm -fr %s" % patchDir)

        # Create a tarball from the tools ISO
        iso = xenrt.rootops.MountISO(localToolsIso)
        mountpoint = iso.getMount()
        toolsTgz = "%s/%s.tgz" % (workdir.path(), tag)
        xenrt.command("cd %s; tar -czf %s *" % (mountpoint, toolsTgz))
        iso.unmount()

        # Clone the template VM
        templateVM = self.getGuest(template)
        guest = templateVM.cloneTemplate(name=tag)
        host.addGuest(guest)

        # Install drivers
        guest.start()
        guest.installDrivers(source=toolsTgz, expectUpToDate=False)

        # Shutdown the clone
        guest.shutdown()
        xenrt.TEC().registry.guestPut(tag, guest)

class TCTestDriverUpgrade(xenrt.TestCase):
    """Test upgrading the drivers in the guest"""

    def run(self, arglist):
        args = xenrt.util.strlistToDict(arglist)
        hotfixTag = args["tag"]

        # Find the VM and snapshot it
        guest = self.getGuest(hotfixTag)
        if not guest:
            raise xenrt.XRTError("Can't find guest %s" % hotfixTag)
        self.guest = guest
        snapshot = guest.snapshot()

        xenrt.TEC().logdelimit("Testing normal driver upgrade")
        guest.start()

        # Try upgrading drivers
        guest.installDrivers()

        # Revert to snapshot, make existing drivers boot start
        xenrt.TEC().logdelimit("Reverting to snapshot")
        guest.shutdown()
        guest.revert(snapshot)

        xenrt.TEC().logdelimit("Testing boot start driver upgrade")
        guest.start()
        guest.setDriversBootStart()

        # Try upgrading drivers
        try:
            guest.installDrivers()
        except xenrt.XRTFailure, e:
            if e.reason.startswith("VIF and/or VBD PV device not used") and xenrt.TEC().lookup("WORKAROUND_CA159586", False, boolean=True):
                # The VM may need some extra reboots
                failCount = 1
                while True:
                    try:
                        guest.reboot()
                        break
                    except:
                        failCount += 1
                        if failCount >= 5:
                            raise
                guest.checkPVDevices()
            else:
                raise

    def postRun(self):
        try:
            self.guest.shutdown()
        except:
            pass

