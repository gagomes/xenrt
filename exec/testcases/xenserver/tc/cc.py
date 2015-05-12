import time, os, os.path, re, string, socket, subprocess, traceback, sys
import xenrt, xenrt.util, xenrt.lib.xenserver
import xmlrpclib 

class _CCBase(xenrt.TestCase):

    EXTLINUX = '/boot/extlinux.conf'

class _SSLCert(xenrt.TestCase):

    def configureSSL(self, hosts):
        self.ca = xenrt.ssl.CertificateAuthority() 
        self.pems = {}
        for host in hosts:
            self.pems[host.getName()] = self.ca.createHostPEM(host, 
                                                              cn=host.getIP(),
                                                              sanlist=["127.0.0.1"])

    def disableSSL(self, hosts):
        for host in hosts:
            try: host.disableSSLVerification()
            except: pass
            try: host.uninstallPEM(waitForXapi=True)
            except: pass
            try: host.uninstallCertificate(self.ca.certificate)
            except: pass
            
    def enableSSL(self, hosts):
        self.disableSSL(hosts)
        for host in hosts:
            host.installCertificate(self.ca.certificate)
            host.installPEM(self.pems[host.getName()])
            host.enableSSLVerification()
        
    def isSSLEnabled(self, hosts):
        for host in hosts:
            if not host.isSSLVerificationEnabled():
                xenrt.TEC().logverbose("SSL is not enabled.")
                return False   
            if not host.isPEMInstalled(self.pems[host.getName()]):
                xenrt.TEC().logverbose("SSL is not enabled.")
                return False   
            if not host.isCertificateInstalled(self.ca.certificate):
                xenrt.TEC().logverbose("SSL is not enabled.")
                return False  
        xenrt.TEC().logverbose("SSL verfication is enabled.")
        return True

class TC11930(_SSLCert):
    """Verify certificate validation functions in presence of IPv6 DNS entry"""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.pool = xenrt.lib.xenserver.poolFactory\
                        (self.host.productVersion)\
                        (self.host)

        # Set up DNS server to return IPv4 entry pointing to controller, and
        # IPv6 entry pointing to controller's IPv4 equivalent address
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            dns = self.host.createBasicGuest(distro="debian60")
        else:
            dns = self.host.createBasicGuest(distro="debian50")
        dns.execguest("apt-get install bind9 -y --force-yes")
        zonefile = """$ORIGIN .
$TTL 38400
xenrt                   IN SOA  ns1.xenrt. patchman.xensource.com. (
                                2010072901
                                10800
                                3600
                                604800
                                38400
                                )
                        NS      ns1.xenrt.
$ORIGIN xenrt.
ns1                     A       %s
fakekirkwood            A       %s
fakekirkwood            AAAA    ::ffff:%s
""" % (dns.getIP(),xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"),xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"))
        revip = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS").split(".")
        revip.reverse()
        revip = string.join(revip, ".")
        revzone = """$ORIGIN .
$TTL 38400
%s.in-addr.arpa.        IN SOA  ns1.xenrt. patchman.xensource.com. (
                                2010073001
                                10800
                                3600
                                604800
                                38400
                                )
                        NS      ns1.xenrt.
$ORIGIN in-addr.arpa.
%s                      PTR     fakekirkwood.xenrt.
""" % (revip, revip)
        fn = xenrt.TEC().tempFile()
        fn2 = xenrt.TEC().tempFile()
        f = file(fn,"w")
        f.write(zonefile)
        f.close()
        f = file(fn2,"w")
        f.write(revzone)
        f.close()
        sftp = dns.sftpClient()
        sftp.copyTo(fn, "/etc/bind/xenrt.hosts")
        sftp.copyTo(fn2, "/etc/bind/reverse.hosts")
        sftp.close()        
        dns.execguest("echo 'zone \"xenrt\" {' >> /etc/bind/named.conf")
        dns.execguest("echo '    type master;' >> /etc/bind/named.conf")
        dns.execguest("echo '    file \"/etc/bind/xenrt.hosts\";' >> /etc/bind/named.conf")
        dns.execguest("echo '};' >> /etc/bind/named.conf")
        #dns.execguest("echo 'zone \"%s.in-addr.arpa\" {' >> /etc/bind/named.conf" % (revip))
        #dns.execguest("echo '    type master;' >> /etc/bind/named.conf")
        #dns.execguest("echo '    file \"/etc/bind/reverse.hosts\";' >> /etc/bind/named.conf")
        #dns.execguest("echo '};' >> /etc/bind/named.conf")
        dns.execguest("rndc reload")

        # Generate a suitable certificate for WLB
        self.configureSSL([self.host])
        pemfn = self.ca.createPEM("fakekirkwood.xenrt", self.host.password,
                                  cn="fakekirkwood.xenrt")
        f = file(pemfn,"r")
        pem = f.read()
        f.close()

        # Set up fake kirkwood        
        self.kirkwood = xenrt.lib.createFakeKirkwood(cert=pem, key=pem)

        # Set up certificate verification on the host
        self.enableSSL([self.host])

        # Enable WLB certificate verification
        self.pool.paramSet("wlb-verify-cert", "true")

        # Point the host at the new DNS server
        self.host.setDNSServer(dns.getIP())

    def run(self, arglist):
        # Try and enable wlb
        try:
            self.pool.initialiseWLB("fakekirkwood.xenrt:%s" % (self.kirkwood.port), "user", "pass")
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.TEC().logverbose("Got exception %s attempting to initialise "
                                   "WLB" % (str(e)))
            raise xenrt.XRTFailure("Unable to initialise WLB with certificate "
                                   "validation enabled in presence of IPv6 DNS "
                                   "entry")

class _CCSetup(_SSLCert, _CCBase):

    LICENSE_SERVER_REQUIRED = True
    LICENSE = "valid-platinum"
    EDITION = "platinum"
    NETWORK = """      <NETWORK>
        <PHYSICAL network="NPRI">
          <NIC/>
          <MANAGEMENT/>
        </PHYSICAL>
        <PHYSICAL network="NSEC">
          <NIC/>
          <VMS/>
        </PHYSICAL>
        <PHYSICAL network="IPRI">
          <NIC/>
          <STORAGE/>
        </PHYSICAL>
      </NETWORK>"""

    def getGuestBridge(self, host):
        return host.getPrimaryBridge()

    def isLicensed(self, host):
        if host.getLicenseDetails()["edition"] == self.EDITION:
            return True
        else:
            return False
   
    def license(self, host):
        host.license(edition=self.EDITION, 
                     v6server=self.licenseServer)

    def configureForCC(self):
        if self.pool:
            if not len(self.hosts) == 2:
                raise xenrt.XRTError("CC expects a pool of two hosts.")
            if not self.pool.isConfiguredForCC():
                self.pool.configureForCC()
                if not self.pool.isSSLVerificationEnabled():
                    self.configureSSL(self.pool.getHosts())
                    self.pool.enableSSLVerification()
        else:
            for h in self.hosts:
                h.configureForCC()

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.pool = self.getDefaultPool()
        self.hosts = map(xenrt.TEC().registry.hostGet, 
                         sorted(filter(re.compile("RESOURCE_HOST_\d+").search, 
                                       xenrt.TEC().registry.hostList())))

        # Always make sure we have a license server available
        self.licenseServerAddress = xenrt.TEC().lookup("EXTERNAL_LICENSE_SERVER", None)
        if self.LICENSE_SERVER_REQUIRED and not self.licenseServerAddress:
            raise xenrt.XRTError("CC expects an external license server.")
        elif self.licenseServerAddress:
            guest = xenrt.TEC().registry.guestGet("LICENSE_SERVER")
            if not guest:
                guest = xenrt.GenericGuest(self.licenseServerAddress)
                guest.mainip = self.licenseServerAddress
                guest.windows = True
                xenrt.TEC().registry.guestPut("LICENSE_SERVER", guest)
            self.licenseServer = guest.getV6LicenseServer(useEarlyRelease=False, install=False)
 
        if xenrt.TEC().lookup("ENFORCE_CC_RESTRICTIONS", False):
            self.configureForCC()

    def installUtilInGuest(self, guest, dest, util = "fill"):
        srcfile = os.path.expanduser("~/xenrt.git/progs/%s/%s.c" % (util, util))
        guest.sftpClient().copyTo(srcfile, "/root/%s.c" % (util,), preserve=False)
        guest.execguest("gcc /root/%s.c --static -Wall -O2 -o %s/%sguest" % (util, dest, util))

    def checkProcessRunning(self, guest, psname):
        return len(guest.execguest("ps -ael | grep '%s'" % psname).strip()) > 0

class _TCXenCCRestriction(_CCSetup):

    DISTRO = None

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        if self.DISTRO == "windows":
            self.guest = self.host.createGenericWindowsGuest(name=self.DISTRO)
        elif self.DISTRO == "linux":
            if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
                self.guest = self.host.createBasicGuest(distro="debian60", name=self.DISTRO)
            else:
                self.guest = self.host.createBasicGuest(distro="debian50", name=self.DISTRO)
        else:
            self.guest = self.host.createBasicGuest(self.DISTRO, name=self.DISTRO)
        self.uninstallOnCleanup(self.guest)
        if self.guest.getState() == 'DOWN': 
            self.guest.start()
        self.guest.preCloneTailor()
        self.guest.shutdown()
        self.guest.setStaticMemRange(0, self.guest.memget())
        self.guestcc = self.guest.cloneVM(name=self.guest.name + "-cc")
        self.uninstallOnCleanup(self.guestcc)

    def memtweak(self, guest):
        guest.start()
        memorigin = guest.getMemoryActual()
        guest.setMemoryTarget(min(int(memorigin * 0.9), memorigin - 10 * xenrt.MEGA))
        try:
            guest.waitForTarget(120)
            xenrt.TEC().logverbose("Guest successfully returned memory.")
            result = True
        except Exception:
            if guest.getState() != 'UP':
                xenrt.TEC().logverbose("Guest no longer running after "
                                       "trying to return memory.")
                result = False
            else:
                memlater = guest.getMemoryActual()
                if memlater == memorigin:
                    xenrt.TEC().logverbose("Guest is still running after "
                                           "trying to return memory but no "
                                           "memory has been actually returned.")
                    result = False

                else: 
                    xenrt.TEC().logverbose("Original memory: %d, "
                                           "Target memory: %d, "
                                           "Current memory: %d. " %
                                           (memorigin, guest.getMemoryTarget(), memlater))
                    if memlater < memorigin:
                        xenrt.TEC().warning("Guest partly returned the memory.")
                        result = True

                    else:
                        xenrt.TEC().warning("Guest memory increased!")
                        result = False
        guest.shutdown(force=True)
        return result

    def run(self, arglist):

        xenrt.TEC().progress("Verify guest can return memory voluntarily "
                             "without CC restriction.")
        if self.host.isCCEnabled():
            self.host.disableCC()
        if self.memtweak(self.guest):
            xenrt.TEC().logverbose("Guest can return memory voluntarily "
                                   "without CC restriction.")
        else:
            raise xenrt.XRTFailure("Guest can not return memory voluntarily "
                                   "even without CC restriction.")
        
        xenrt.TEC().progress("Verify guest can not return memory voluntarily "
                             "with CC restriction.")
        if not self.host.isCCEnabled():
            self.host.enableCC()
        if self.memtweak(self.guestcc):
            raise xenrt.XRTFailure("Guest can return memory voluntarily "
                                   "even with CC restriction.")
        else:
            xenrt.TEC().logverbose("Guest can not return memory voluntarily "
                                   "with CC restriction.")

class TC10795(_TCXenCCRestriction):
    """Verify Windows guest can not return memory pages to Xen with CC restriction turned on"""
    DISTRO = "windows"
            
class TC10796(_TCXenCCRestriction):
    """Verify Linux guest can not return memory pages to Xen with CC restriction turned on"""
    DISTRO = "linux"

class _SSLBase(_CCSetup):

    EXPIRED = False
    VALID = True 
    SETUP_ETC_HOSTS = True

    def getExpiredHost(self, host):
        return False

    def getCN(self, host):
        return host.getIP()

    def getSANs(self, host):
        return ["127.0.0.1"]

    def checkConnection(self, source, destination, expect, description):
        dest_name = destination.getMyHostName()
        dest_ip = destination.getIP()
        dest_cert_addrs = [self.getCN(destination)] + self.getSANs(destination)
        dest_addr = (dest_name in dest_cert_addrs) and dest_name or None
        if dest_addr is None:
            dest_addr = ("%s.xenrt" % (dest_name) in dest_cert_addrs) and "%s.xenrt" % (dest_name) or dest_ip
        command = "xe%s host-is-in-emergency-mode -s %s -u root -pw %s" % \
                  (self.debug_on_fail, dest_addr, destination.password)
        xenrt.TEC().logverbose("Testing connection from %s to %s." %
                               (source.getName(), destination.getName()))
        try:
            source.execdom0(command)
            result = True
        except:
            result = False
        message = description + ": " + "We expected the connection to be %s and it is %s." % \
                                       (expect and "accepted" or "refused",
                                        result and "accepted" or "refused")
        if result == expect:
            xenrt.TEC().logverbose(message)
        else:
            raise xenrt.XRTFailure(message)

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        assert len(self.hosts) >= 2
        try:
            self.hosts[0].execdom0("xe --debug-on-fail pool-list")
            self.debug_on_fail = " --debug-on-fail"
        except:
            self.debug_on_fail = ""
        self.disableSSL(self.hosts)
        self.ca = xenrt.ssl.CertificateAuthority(expired=self.EXPIRED)
        self.pems = {}
        for host in self.hosts:
            self.pems[host.getName()] = self.ca.createHostPEM(host, 
                                                              cn=self.getCN(host),
                                                              sanlist=self.getSANs(host),   
                                                              expired=self.EXPIRED)
            if self.SETUP_ETC_HOSTS:
                for h in self.hosts:
                    h.execdom0("echo %s %s >> /etc/hosts" % (host.getIP(), host.getName()))
            else:
                for h in self.hosts:
                    h.execdom0("grep -v '%s %s' /etc/hosts > /tmp/newhosts; "
                               "mv /tmp/newhosts /etc/hosts" % (host.getIP(), host.getName()))

    def postRun(self):
        self.disableSSL(self.hosts)

class TC10940(_SSLBase):
    """ SSL certificate verification between independent hosts."""
                                                         
    def prepare(self, arglist):
        _SSLBase.prepare(self, arglist)
        self.hostA = self.hosts[0]
        self.hostB = self.hosts[1]

        # If we currently have a pool, get rid of it
        if self.pool:
            self.pool.resetSSL()
            for h in self.pool.getSlaves():
                self.pool.eject(h)
            self.pool = None

        # Make sure all hosts are correctly licensed and have SSL verification turned off
        for h in self.hosts:
            h.license(edition=self.EDITION, v6server=self.licenseServer)

        # Disable SSL verification on all hosts
        self.disableSSL(self.hosts)

    def run(self, arglist):
        xenrt.TEC().progress("Step 1: Both hosts with default setting.")
        self.checkConnection(self.hostA, self.hostB, True, "Step 1")
        self.checkConnection(self.hostB, self.hostA, True, "Step 1")

        xenrt.TEC().progress("Step 2: Enable verification on %s, but not on %s." % 
                             (self.hostA.getName(), self.hostB.getName()))
        self.hostA.enableSSLVerification()
        self.checkConnection(self.hostA, self.hostB, False, "Step 2")
        self.checkConnection(self.hostB, self.hostA, True, "Step 2")

        xenrt.TEC().progress("Step 3: Install/trust CA's certificate on both hosts.")
        self.hostA.installCertificate(self.ca.certificate)
        self.hostB.installCertificate(self.ca.certificate)
        self.checkConnection(self.hostA, self.hostB, False, "Step 3")
        self.checkConnection(self.hostB, self.hostA, True, "Step 3")

        xenrt.TEC().progress("Step 4: Install new SSL key (whose CA we trust) on both hosts.")
        self.hostA.installPEM(self.pems[self.hostA.getName()], waitForXapi=True)
        self.hostB.installPEM(self.pems[self.hostB.getName()], waitForXapi=True)
        time.sleep(60) # Allow 60 seconds to let the hosts stabilise
        self.checkConnection(self.hostA, self.hostB, self.VALID, "Step 4")
        self.checkConnection(self.hostB, self.hostA, True, "Step 4")

        xenrt.TEC().progress("Step 5: Revert verification setting on both "
                             "hosts: Disable on %s, enable on %s." % 
                             (self.hostA.getName(), self.hostB.getName()))
        self.hostA.disableSSLVerification()
        self.hostB.enableSSLVerification()
        self.checkConnection(self.hostA, self.hostB, True, "Step 5")
        self.checkConnection(self.hostB, self.hostA, self.VALID, "Step 5")

class TC11228(TC10940):
    """SSL verification with different certificate settings."""

    # We use proper DNS so we don't want to put in fake hosts entries
    SETUP_ETC_HOSTS = False

    def prepare(self, arglist):
        TC10940.prepare(self, arglist)

        # Set up DNS server, and configure hosts to use it
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            dns = self.hostA.createBasicGuest(distro="debian60")
        else:
            dns = self.hostA.createBasicGuest(distro="debian50")
        self.uninstallOnCleanup(dns)
        # Move the DNS server to the management network
        dns.shutdown()
        dns.changeVIF("eth0", bridge="xenbr0")
        dns.start()

        dns.execguest("apt-get install bind9 -y --force-yes")
        zonefile = """$ORIGIN .
$TTL 38400
xenrt                   IN SOA  ns1.xenrt. patchman.xensource.com. (
                                2010072901
                                10800
                                3600
                                604800
                                38400
                                )
                        NS      ns1.xenrt.
$ORIGIN xenrt.
"""

        # Identify the subnet to use
        revip = self.hostA.getIP().split(".")
        revip.reverse()
        revsubnet = string.join(revip[1:], ".")

        revzone = """$ORIGIN .
$TTL 38400
%s.in-addr.arpa.        IN SOA  ns1.xenrt. patchman.xensource.com. (
                                2010073001
                                10800
                                3600
                                604800
                                38400
                                )
                        NS      ns1.xenrt.
$ORIGIN %s.in-addr.arpa.
""" % (revsubnet, revsubnet)

        # Add the hosts
        for h in [self.hostA, self.hostB]:
            zonefile += "%s    A    %s\n" % (h.getName(), h.getIP())
            revzone += "%s    PTR    %s.xenrt.\n" % (h.getIP().split(".")[3], h.getName())

        # Write the zone files
        fn = xenrt.TEC().tempFile()
        fn2 = xenrt.TEC().tempFile()
        f = file(fn,"w")
        f.write(zonefile)
        f.close()
        f = file(fn2,"w")
        f.write(revzone)
        f.close()
        sftp = dns.sftpClient()
        sftp.copyTo(fn, "/etc/bind/xenrt.hosts")
        sftp.copyTo(fn2, "/etc/bind/reverse.hosts")
        sftp.close()
        dns.execguest("echo 'zone \"xenrt\" {' >> /etc/bind/named.conf")
        dns.execguest("echo '    type master;' >> /etc/bind/named.conf")
        dns.execguest("echo '    file \"/etc/bind/xenrt.hosts\";' >> /etc/bind/named.conf")
        dns.execguest("echo '};' >> /etc/bind/named.conf")
        dns.execguest("cp -f /etc/bind/named.conf /etc/bind/named.nordns.conf")

        dns.execguest("echo 'zone \"%s.in-addr.arpa\" {' >> /etc/bind/named.conf" % revsubnet)
        dns.execguest("echo '    type master;' >> /etc/bind/named.conf")
        dns.execguest("echo '    file \"/etc/bind/reverse.hosts\";' >> /etc/bind/named.conf")
        dns.execguest("echo '};' >> /etc/bind/named.conf")
        dns.execguest("cp -f /etc/bind/named.conf /etc/bind/named.rdns.conf")

        # Reload bind config
        dns.execguest("rndc reload")
        self.dns = dns

        # Configure hosts to use DNS server
        for h in [self.hostA, self.hostB]:
            h.setDNSServer(dns.getIP())

    def generateSANs(self, *configuration):
        sanlist = [lambda host:"127.0.0.1"]
        if "fqdn" in configuration:
            sanlist.append(lambda host:"%s.xenrt" % host.getName())
        if "invalidfqdn" in configuration:
            sanlist.append(lambda host:"missing-%s.xenrt" % host.getName())
        if "ip" in configuration:
            sanlist.append(lambda host:host.getIP())
        if "invalidip" in configuration:
            sanlist.append(lambda host:"169.254.0.255")
        if "noise" in configuration:
            sanlist.append(lambda host:"192.168.0.255")
            sanlist.append(lambda host:"noisy.xenrt")
        return lambda host:map(lambda x:x(host), sanlist)

    def generateCN(self, *configuration):
        if "fqdn" in configuration:
            return lambda host:"%s.xenrt" % host.getName()
        if "invalidfqdn" in configuration:
            return lambda host:"missing-%s.xenrt" % host.getName()
        if "ip" in configuration:
            return lambda host:host.getIP()
        if "invalidip" in configuration:
            return lambda host:"169.254.0.255"
        return lambda host:""

    def iteration(self):
        TC10940.prepare(self, [])
        TC10940.run(self, [])

    def run(self, arglist):
        valid = [("CN: FQDN SANs: IP", #0
                 ["fqdn"], ["ip"]),
                 ("CN: FQDN SANs: IP,XIP,XFQDN", #3
                 ["fqdn"], ["ip", "noise"]),
                 ("CN: FQDN SANs: IP,XFQDN", #5
                 ["fqdn"], ["ip", "invalidfqdn"]),
                 ("CN: FQDN SANs: IP,FQDN,XIP,XFQDN", #6
                 ["fqdn"], ["ip", "fqdn", "noise"]),
                 ("CN: FQDN SANs: IP,XFQDN,XIP,XFQDN", #9
                 ["fqdn"], ["ip", "invalidfqdn", "noise"]),
                 ("CN: IP SANs: XIP,XFQDN", #13
                 ["ip"], ["noise"]),
                 ("CN: IP SANs: IP", #15
                 ["ip"], ["ip"]),
                 ("CN: IP SANs: FQDN", #16
                 ["ip"], ["fqdn"])
                ]

        invalid = [("CN: XFQDN SANs: XIP",
                   ["invalidfqdn"], ["invalidip"]),
                   ("CN: XFQDN SANs: XFQDN",
                   ["invalidfqdn"], ["invalidfqdn"]),
                   ("CN: XFQDN SANs: None",
                   ["invalidfqdn"], []),
                   ("CN: XIP SANs: None",
                   ["invalidip"], [])]

        for i in range(len(valid)):
            description, cnconfiguration, sanconfiguration = valid[i]
            self.VALID = True
            self.getCN = self.generateCN(*cnconfiguration)
            self.getSANs = self.generateSANs(*sanconfiguration)
            xenrt.TEC().logverbose("Testing host key which is expected to succeed. (%s)" % (description))
            self.runSubcase("iteration", (), "Valid", i)

        for i in range(len(invalid)):
            description, cnconfiguration, sanconfiguration = invalid[i]
            self.VALID = False
            self.getCN = self.generateCN(*cnconfiguration)
            nordns = sanconfiguration is None
            if nordns:
                # We want to break rDNS
                self.dns.execguest("cp -f /etc/bind/named.nordns.conf /etc/bind/named.conf")
                self.dns.execguest("rndc reload")
                sanconfiguration = []
            self.getSANs = self.generateSANs(*sanconfiguration)
            xenrt.TEC().logverbose("Testing host key which is expected to fail. (%s)" % (description))
            self.runSubcase("iteration", (), "Invalid", i)
            if nordns:
                self.dns.execguest("cp -f /etc/bind/named.rdns.conf /etc/bind/named.conf")
                self.dns.execguest("rndc reload")

    def postRun(self):
        TC10940.postRun(self)

        if self.dns:
            # Clear up rDNs config
            for h in [self.hostA, self.hostB]:
                h.removeDNSServer(self.dns.getIP())

class TC11229(TC10940):
    """Test an expired SSL certificate fails."""

    EXPIRED = True
    VALID = False
 
class TC10941(_SSLBase):
    """ SSL certificates verification in pool joining."""

    def prepare(self, arglist=[]):
        _SSLBase.prepare(self, arglist=arglist)
        assert len(self.hosts) >= 2
        if not self.pool or len(self.pool.getSlaves()) == 0:
            self.master = self.hosts[0]
            self.slave = self.hosts[1]
            self.pool = xenrt.lib.xenserver.poolFactory\
                        (self.master.productVersion)\
                        (self.master)
        else:
            self.master = self.pool.master
            self.slave = self.pool.getSlaves()[0]
            self.pool.eject(self.slave)
            self.pool.resetSSL()
            self.configureForCC()
            self.slave.license(edition=self.EDITION, v6server=self.licenseServer)

        self.disableSSL(self.hosts)
        self.getLogsFrom(self.master)
        self.getLogsFrom(self.slave)
 
    def poolJoin(self, expect, desc=None, catch=None):

        desc = desc and desc + ": " or ""
        
        try:
            self.pool.addHost(self.slave)
            result = True
        except Exception, e:
            exceptionOK = False
            if catch:
                for c in catch:
                    if re.search(c,(e.reason or "") + (e.data or "")):
                        xenrt.TEC().logverbose(desc + "Expected failure: %s" % e)
                        result = False
                        exceptionOK = True
                        break
            if not exceptionOK:
                xenrt.TEC().logverbose(desc + "Unexpected error: %s" % e)
                raise e
        else:
            self.pool.check()
            self.pool.eject(self.slave)
            self.slave.license(edition=self.EDITION, v6server=self.licenseServer)
            
        msg = desc + "We expect the pool joining to be %s and it is %s." \
              % (expect and "accepted" or "refused",
                 result and "accepted" or "refused")

        if result == expect:
            xenrt.TEC().logverbose(msg)
        else:
            raise xenrt.XRTFailure(msg)
   
        if xenrt.TEC().lookup("ENFORCE_CC_RESTRICTIONS", False):
            for host in self.hosts:
                if not self.isLicensed(host):
                    self.license(host)
                self.host.configureForCC()

    def run(self, arglist=[]):

        xenrt.TEC().progress("Step 1: both master and slave with default setting.")
        self.poolJoin(True, desc="Step 1")

        # Pool eject causes the firstboot script to run and enable verification on both hosts
        for h in self.hosts:
            h.disableSSLVerification()

        xenrt.TEC().progress("Step 2: enable verification on slave.")
        self.slave.enableSSLVerification()
        self.poolJoin(False, desc="Step 2", catch=["There was an error connecting to the host","Stunnel_connection_failed"])
        
        xenrt.TEC().progress("Step 3: install CA's certificate on slave.")
        self.slave.installCertificate(self.ca.certificate)
        self.poolJoin(False, desc="Step 3", catch=["There was an error connecting to the host","Stunnel_connection_failed"])

        xenrt.TEC().progress("Step 4: install new SSL key (whose CA slave trusts) on master.")
        self.master.installPEM(self.pems[self.master.getName()])
        self.poolJoin(True, desc="Step 4")

        xenrt.TEC().progress("Step 5: install CA's certificate and enable verification on master.")
        self.master.installCertificate(self.ca.certificate)
        self.master.enableSSLVerification()
        # For now, do not try at this point, otherwise we'll get into a dubious
        # status hard to recover, as the slave would think it has succeeded
        # in joining the pool, however the master would not be able to talk to it
        # self.poolJoin(False, desc="Step 5", catch=".*")

        xenrt.TEC().progress("Step 6: install new SSL key (whose CA master trusts) on slave.")
        self.slave.installPEM(self.pems[self.slave.getName()])
        self.checkConnection(self.slave, self.master, True, "Before pool-join (slave -> master).")
        self.checkConnection(self.master, self.slave, True, "Before pool-join (master -> slave).")
        self.poolJoin(True, desc="Step 6")

    def postRun(self):
        _SSLBase.postRun(self)
        if xenrt.TEC().lookup("ENFORCE_CC_RESTRICTIONS", False):
            self.pool.addHost(self.slave)

class TC11008(_SSLBase):
    """ Seamlessly enable/disable SSL certificates verification in a running pool  """

    def prepare(self, arglist=[]):
        _SSLBase.prepare(self, arglist=arglist)
        assert len(self.hosts) >= 2
        self.master = self.hosts[0]
        self.slave = self.hosts[1]
        xenrt.TEC().logverbose(xenrt.TEC().registry.hostList())
        xenrt.TEC().logverbose(map(lambda x:x.getName(), self.hosts))
        if not self.pool:
            self.pool = xenrt.lib.xenserver.poolFactory\
                        (self.master.productVersion)\
                        (self.master)
            self.pool.addHost(self.slave)
            self.pool.resetSSL()
        else:
            self.pool.resetSSL()
            self.configureForCC()

    def run(self, arglist=[]):
        self.master.installPEM(self.pems[self.master.getName()])
        self.pool.check()
        self.slave.installPEM(self.pems[self.slave.getName()])
        self.pool.check()
        self.master.installCertificate(self.ca.certificate)
        self.pool.check()
        self.pool.synchroniseCertificates()
        self.pool.check()
        self.master.enableSSLVerification()
        self.pool.check()
        self.slave.enableSSLVerification()
        self.pool.check()
        self.pool.eject(self.slave)
        self.slave.license(edition=self.EDITION, v6server=self.licenseServer)
        self.pool.check()
        self.checkConnection(self.slave, self.master, True, "Before pool-join (slave -> master).")
        self.checkConnection(self.master, self.slave, True, "Before pool-join (master -> slave).")
        self.pool.addHost(self.slave)
        self.pool.check()
        self.master.disableSSLVerification()
        self.pool.check()
        self.slave.disableSSLVerification()
        self.pool.check()
        self.master.uninstallCertificate(self.ca.certificate)
        self.pool.check()
        self.pool.synchroniseRootCertificates()
        self.pool.check()
        self.pool.eject(self.slave)
        self.slave.license(edition=self.EDITION, v6server=self.licenseServer)
        self.pool.check()
        self.checkConnection(self.slave, self.master, True, "Before pool-join (slave -> master).")
        self.checkConnection(self.master, self.slave, True, "Before pool-join (master -> slave).")
        self.pool.addHost(self.slave)
        self.pool.check()

class TC11214(_CCSetup):
    """Check that XenAPI verifies the username and password before executing API calls."""

    INVALID = "invalidpassword"
    INVALID_PTOKEN = "97c238de-ada4-b3c5-2b04-185ad6e41f0c/" \
                     "2b01d385-f5a8-6141-c2ae-4d33340a6994/" \
                     "b5bec734-7f34-36df-7d94-2b99af8481fc"

    def check(self, xmlrpc, id):
        xenrt.TEC().logverbose("Checking if session %s is valid." % (id))
        try:
            result = xmlrpc.VM.get_all(id)
            if result["Status"] != "Success":
                xenrt.TEC().logverbose("Session %s does not appear to be valid" % (id))
                return False
            xenrt.TEC().logverbose("Session %s is valid." % (id))
            return True
        except Exception, e:
            raise xenrt.XRTFailure("API call failed for an unexpected reason. (%s)" % (str(e)))

    def _test(self, username=None, password=None, ptoken=None, slave=False, local=False):
        try:
            xmlrpc = xmlrpclib.ServerProxy('https://%s:443' % (self.host.getIP()))
            if username and password and not slave:
                result = xmlrpc.session.login_with_password(username, password)
            if username and password and slave:
                result = xmlrpc.session.slave_local_login_with_password(username, password)
            if ptoken and not local: 
                result = xmlrpc.session.slave_login(self.host.getHandle(), ptoken)
            if ptoken and local:
                result = xmlrpc.session.slave_local_login(ptoken)
            if result["Status"] == "Failure":
                raise xenrt.XRTFailure("API call failed: %s" % (result))
            return xmlrpc, result["Value"]
        except Exception, e:
            raise xenrt.XRTFailure("Session create failed. (%s)" % (str(e)))

    def test(self, **kwargs):
        xmlrpc, sessionId = self._test(**kwargs)
        if not self.check(xmlrpc, sessionId):
            raise xenrt.XRTFailure("Session did not appear to be valid")

    def negativeTest(self, **kwargs):
        try:
            self._test(**kwargs)    
        except Exception, e:
            if re.search("SESSION_AUTHENTICATION_FAILED", str(e)):
                xenrt.TEC().logverbose("Authentication with invalid credentials failed.")
            else:
                raise xenrt.XRTFailure("Unexpected exception: %s" % (str(e)))
        else:
            raise xenrt.XRTFailure("Session create with invalid credentials succeeded.")

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        self.ptoken = self.host.execdom0("cat /etc/xensource/ptoken").strip()
    
    def run(self, arglist):
        xenrt.TEC().logverbose("Trying to create session with valid " \
                               "credentials. (root, %s)" % (self.host.password))
        self.test(username="root", password=self.host.password)
        
        xenrt.TEC().logverbose("Trying to create session with valid pool secret. (%s)" % (self.ptoken))
        self.test(ptoken=self.ptoken, local=True)            

        xenrt.TEC().logverbose("Trying to create slave session with valid " \
                               "credentials. (root, %s)" % (self.host.password))
        self.test(username="root", password=self.host.password, slave=True)

        xenrt.TEC().logverbose("Trying to create an internal slave session with valid " \
                               "credentials. (%s)" % (self.ptoken))
        self.test(ptoken=self.ptoken)

        xenrt.TEC().logverbose("Trying to create session with an invalid password. (%s)" % (self.INVALID))
        self.negativeTest(username="root", password=self.INVALID)

        xenrt.TEC().logverbose("Trying to create session with an invalid username. (none)")
        self.negativeTest(username="none", password=self.host.password)

        xenrt.TEC().logverbose("Trying to create slave session with an invalid password. (%s)" % (self.INVALID))
        self.negativeTest(username="root", password=self.INVALID, slave=True)

        xenrt.TEC().logverbose("Trying to create slave session with an invalid username. (none)")
        self.negativeTest(username="none", password=self.host.password, slave=True)

        xenrt.TEC().logverbose("Trying to create session with an invalid pool secret. (%s)" % (self.INVALID_PTOKEN))
        self.negativeTest(ptoken=self.INVALID_PTOKEN, local=True)            

        xenrt.TEC().logverbose("Trying to create an internal slave session with " \
                               "an invalid pool secret. (%s)" % (self.INVALID_PTOKEN))
        self.negativeTest(ptoken=self.INVALID_PTOKEN)

class TC11215(_CCSetup):
    """VMs should not be able to access the XenStore trees of other VMs."""

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        self.guestA = self.host.createGenericWindowsGuest()
        self.guestB = self.host.createGenericWindowsGuest()
        self.uninstallOnCleanup(self.guestA)
        self.uninstallOnCleanup(self.guestB)

    def run(self, arglist):
        xenrt.TEC().logverbose("Try to read another XenStore sub-tree.")
        try:
            self.guestA.xmlrpcExec("\"C:\\Program Files\\Citrix\\XenTools\\xenstore_client.exe\" " \
                                   "read /local/domain/%s/name" % (self.guestB.getDomid()))
        except:
            xenrt.TEC().logverbose("XenStore access failed as expected.")
        else:
            raise xenrt.XRTFailure("XenStore access succeeded.")

        xenrt.TEC().logverbose("Try to write to another XenStore sub-tree.")
        try:
            self.guestA.xmlrpcExec("\"C:\\Program Files\\Citrix\\XenTools\\xenstore_client.exe\" " \
                                   "write /local/domain/%s/name newname" % (self.guestB.getDomid()))
        except:
            xenrt.TEC().logverbose("XenStore access failed as expected.")
        else:
            raise xenrt.XRTFailure("XenStore access succeeded.")

class TC11223(_CCSetup):
    """Test that shared memory channels between VMs are disabled."""

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)

        self.guestA = self.host.createGenericWindowsGuest(drivers=False)
        self.guestB = self.host.createGenericWindowsGuest(drivers=False)
        self.uninstallOnCleanup(self.guestA)
        self.uninstallOnCleanup(self.guestB)

        # We need to use the legacy drivers for this test, as the utility doesn't work with the
        # new drivers
        
        if isinstance(self.guestA, xenrt.lib.xenserver.guest.BostonGuest):
            self.guestA.installDrivers(useLegacy=True)
        else:
            self.guestA.installDrivers()
        
        if isinstance(self.guestB, xenrt.lib.xenserver.guest.BostonGuest):
            self.guestB.installDrivers(useLegacy=True)
        else:
            self.guestB.installDrivers()
      
        driverTar = xenrt.TEC().getFile("xe-phase-1/pvdrivers-build-unsigned.tar.gz",
                                        "xe-phase-1/pvdrivers-build-crosssigned.tar.gz")
        if not driverTar:
            raise xenrt.XRTError("Cannot find build tarball to retrieve xenops_test.exe")

        xenrt.command("tar -C %s -xzf %s" % (xenrt.TEC().getWorkdir(),
                                             driverTar)) 
        self.guestA.xmlrpcSendFile("%s/windows/build/i386/xenops.dll" % (xenrt.TEC().getWorkdir()),
                                   "C:\\Program Files\\Citrix\\XenTools\\xenops.dll")
        self.guestA.xmlrpcSendFile("%s/windows/build/i386/xenops_test.exe" % (xenrt.TEC().getWorkdir()),
                                   "C:\\Program Files\\Citrix\\XenTools\\xenops_test.exe")
        self.guestB.xmlrpcSendFile("%s/windows/build/i386/xenops.dll" % (xenrt.TEC().getWorkdir()),
                                   "C:\\Program Files\\Citrix\\XenTools\\xenops.dll")
        self.guestB.xmlrpcSendFile("%s/windows/build/i386/xenops_test.exe" % (xenrt.TEC().getWorkdir()),
                                   "C:\\Program Files\\Citrix\\XenTools\\xenops_test.exe")

    def run(self, arglist):
        # TODO Ideally we don't want to rely on the grant reference being the same across grants.
        data = self.guestA.xmlrpcExec("\"C:\\Program Files\\Citrix\\XenTools\\xenops_test.exe\" " \
                                    "offer_const %s 2" % (self.guestB.getDomid()), returndata=True)
        xenrt.TEC().logverbose("DATA: %s" % (data))
        match = re.search("reference (?P<gref>\d+)", data)
        if not match:
            raise xenrt.XRTError("No grant reference found.")
        gref = match.group("gref")

        xenrt.TEC().logverbose("Offering grant on VM <a>.") 
        r = self.guestA.xmlrpcStart("\"C:\\Program Files\\Citrix\\XenTools\\xenops_test.exe\" " \
                                    "offer_const %s 0" % (self.guestB.getDomid()))
        data = self.guestA.xmlrpcLog(r)
        xenrt.TEC().logverbose("DATA: %s" % (data))
       
        try:
            xenrt.TEC().logverbose("Trying to map grant on <b>.") 
            self.guestB.xmlrpcExec("\"C:\\Program Files\\Citrix\\XenTools\\xenops_test.exe\" " \
                                   "map_dump %s %s" % (self.guestA.getDomid(), gref))
        except:
            xenrt.TEC().logverbose("Mapping grant failed as expected.")
        else:
            raise xenrt.XRTFailure("Mapped a grant with the CC restrictions enabled.")

    def postRun(self):
        # Enable CC restrictions.
        if not self.host.isCCEnabled():
            self.host.enableCC()

class TC11216(_CCSetup):
    """Check that data written to one VDI cannot be observed in a second VDI on the same SR."""

    PATTERN = "0xCACACACA"

    ITERATIONS = 1
    THRESHOLD = 1.0

    def prepare(self, arglist):
        if xenrt.TEC().lookup("CC_SKIP_LONG_TESTS", False, boolean=True):
            return

        _CCSetup.prepare(self, arglist)
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.guestA = self.host.createBasicGuest(distro="debian60")
            self.guestB = self.host.createBasicGuest(distro="debian60")
        else:
            self.guestA = self.host.createBasicGuest(distro="debian50")
            self.guestB = self.host.createBasicGuest(distro="debian50")
        self.uninstallOnCleanup(self.guestA)
        self.uninstallOnCleanup(self.guestB)
        self.installUtilInGuest(self.guestA, "%s/progs" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), "fill")
        self.installUtilInGuest(self.guestB, "%s/progs" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), "fill")
        
        self.sruuid = self.host.lookupDefaultSR() 
        srsize = int(self.host.genParamGet("sr", self.sruuid, "physical-size"))
        utilisation = int(self.host.genParamGet("sr", self.sruuid, "physical-utilisation"))
        self.vdia = self.guestA.createDisk(sruuid=self.sruuid, 
                                           sizebytes=(srsize-utilisation-xenrt.MEGA)/2, 
                                           returnDevice=True)
        self.vdib = self.guestB.createDisk(sruuid=self.sruuid, 
                                           sizebytes=(srsize-utilisation-xenrt.MEGA)/2, 
                                           returnDevice=True)

    def run(self, arglist):
        if xenrt.TEC().lookup("CC_SKIP_LONG_TESTS", False, boolean=True):
            xenrt.TEC().skip("Skipping TC-11216 due to CC_SKIP_LONG_TESTS")
            return

        self.guestA.execguest("%s/progs/fillguest /dev/%s %s write &> /tmp/write.out &" % 
                              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.vdia, self.PATTERN))
        self.guestB.execguest("%s/progs/fillguest /dev/%s %s read &> /tmp/read.out & " % 
                              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.vdib, self.PATTERN))

        while True:
            time.sleep(60)

            dataA = self.guestA.execguest("cat /tmp/write.out", nolog=True)
            dataB = self.guestB.execguest("cat /tmp/read.out", nolog=True)

            proportion = max(map(float, re.findall("([\d\.]+)%", dataB)) + [0])
            xenrt.TEC().logverbose("Highest incidence of pattern found: %s%%" % (proportion))
            if proportion > self.THRESHOLD:
                raise xenrt.XRTFailure("Unacceptable proportion of %s found: %s%%" %
                                       (self.PATTERN, proportion))

            iterationA = max(map(int, re.findall("Iteration (\d+)", dataA)) + [0])
            iterationB = max(map(int, re.findall("Iteration (\d+)", dataB)) + [0])
            iteration = max([iterationA, iterationB])
            if iteration >= self.ITERATIONS:
                xenrt.TEC().logverbose("Test completed successfully.") 
                break
            if not self.checkProcessRunning(self.guestA, "fillguest"):
                raise xenrt.XRTError("fill program halted before finishing its task from guestA.")
            if not self.checkProcessRunning(self.guestB, "fillguest"):
                raise xenrt.XRTError("fill program halted before finishing its task from guestB.")

class TC11222(_CCSetup):
    """Check that data is zeroed temporally."""

    PATTERN = "0xCACACACA"  

    THRESHOLD = 1.0           

    # NFS won't report free space correctly.
    NFSCONTINGENCY = 0.6

    # Specify a maximum duration for the fill program in hours
    FILLTIMEOUT = 72

    def removeVDI(self, vdiuuid):
        cli = self.host.getCLIInstance()
        cli.execute("vdi-destroy", "uuid=%s" % (vdiuuid))

    def prepare(self, arglist):
        if xenrt.TEC().lookup("CC_SKIP_LONG_TESTS", False, boolean=True):
            return

        _CCSetup.prepare(self, arglist)
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.guestA = self.host.createBasicGuest(distro="debian60")
            self.guestB = self.host.createBasicGuest(distro="debian60")
        else:
            self.guestA = self.host.createGenericLinuxGuest()
            self.guestB = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guestA)
        self.uninstallOnCleanup(self.guestB)
        self.installUtilInGuest(self.guestA, "%s/progs" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), "fill")
        self.installUtilInGuest(self.guestB, "%s/progs" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), "fill")
        
        self.sruuid = self.host.lookupDefaultSR() 
        self.srsize = int(self.host.genParamGet("sr", self.sruuid, "physical-size"))
        self.vbduuid = self.guestA.createDisk(sruuid=self.sruuid, 
                                              sizebytes=int(self.srsize*self.NFSCONTINGENCY), 
                                              returnVBD=True)
        
    def run(self, arglist):
        if xenrt.TEC().lookup("CC_SKIP_LONG_TESTS", False, boolean=True):
            xenrt.TEC().skip("Skipping TC-11222 due to CC_SKIP_LONG_TESTS")
            return

        vdiuuid = self.host.genParamGet("vbd", self.vbduuid, "vdi-uuid")
        device = self.host.genParamGet("vbd", self.vbduuid, "device")
         
        self.guestA.execguest("%s/progs/fillguest /dev/%s %s write &> /tmp/write.out &" % 
                              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), device, self.PATTERN))
        fillstart = xenrt.util.timenow()
        while True:
            time.sleep(60)
            dataA = self.guestA.execguest("cat /tmp/write.out", nolog=True)  
            iterationA = max(map(int, re.findall("Iteration (\d+)", dataA)) + [0])
            if iterationA > 1:
                break
            if ((xenrt.util.timenow() - fillstart) / 3600) > self.FILLTIMEOUT:
                raise xenrt.XRTError("fill program timed out after %d hours" % (self.FILLTIMEOUT))
            if not self.checkProcessRunning(self.guestA, "fillguest"):
                raise xenrt.XRTError("fill program halted before finishing its task.")
       
        self.guestA.shutdown() 
        self.removeVDI(vdiuuid)

        self.vbduuid = self.guestB.createDisk(sruuid=self.sruuid, sizebytes=self.srsize, returnVBD=True)
        vdiuuid = self.host.genParamGet("vbd", self.vbduuid, "vdi-uuid")
        device = self.host.genParamGet("vbd", self.vbduuid, "device")
        
        self.guestB.execguest("%s/progs/fillguest /dev/%s %s read &> /tmp/read.out & " % 
                              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), device, self.PATTERN))
        fillstart = xenrt.util.timenow()
        while True:
            time.sleep(60)

            dataB = self.guestB.execguest("cat /tmp/read.out", nolog=True) 
            proportion = max(map(float, re.findall("([\d\.]+)%", dataB)) + [0.0])
            xenrt.TEC().logverbose("Highest incidence of pattern found: %s%%" % (proportion))
            if proportion > self.THRESHOLD:
                raise xenrt.XRTFailure("Unacceptable proportion of %s found: %s%%" % 
                                       (self.PATTERN, proportion))
            iteration = max(map(int, re.findall("Iteration (\d+)", dataB)) + [0])
            if iteration >= 1:
                xenrt.TEC().logverbose("Test completed successfully.") 
                break
            if ((xenrt.util.timenow() - fillstart) / 3600) > self.FILLTIMEOUT:
                raise xenrt.XRTError("fill program timed out after %d hours" % (self.FILLTIMEOUT))
            if not self.checkProcessRunning(self.guestB, "fillguest"):
                raise xenrt.XRTError("fill program halted before finishing its task.")


class TC11227(TC11222):
    """Temporal VDI separation under resize"""

    def removeVDI(self, vdiuuid):
        cli = self.host.getCLIInstance()
        cli.execute("vdi-resize", "uuid=%s disk-size=1" % (vdiuuid))
 
class TC11221(_CCSetup):
    """Storage network separation"""

    STORAGE_PATTERN = "0xCACACACA"
    GUEST_PATTERN = "0x45464748"
    MANAGEMENT_PATTERN = "0x50515253" 

    GUEST_PORT = 11111
    MANAGEMENT_PORT = 11112

    def ascii(self, pattern):
        t = [ pattern[2*i:2*i+2] for i in xrange(len(pattern)/2) ][1:]
        t = map(chr, map(lambda x:int(x, 16), t))
        return string.join(t, "")

    def hex(self, pattern):
        return int(pattern, 16)

    def checkStorageTraffic(self):
        if self.guest.execguest("pgrep [f]ill", retval="code"):
            xenrt.TEC().logverbose("No storage traffic is being generated.")
            return False
        else:
            xenrt.TEC().logverbose("Storage traffic is being generated.")
            return True

    def startStorageTraffic(self):
        if self.checkStorageTraffic():
            self.stopStorageTraffic()
        if self.guest.execguest("ls /dev/xvdc", retval="code"):
            self.guest.createDisk(sizebytes=1024*1024*1024, userdevice="xvdc", sruuid="DEFAULT")
        xenrt.TEC().logverbose("Starting storage traffic.")
        self.guest.execguest("%s/progs/fillguest /dev/xvdc %s write &> /tmp/fill.out < /dev/null &" % 
                             (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), self.STORAGE_PATTERN))
        xenrt.sleep(3)
        if not self.checkProcessRunning(self.guest, "fillguest"):
            raise xenrt.XRTError("fill program halted before finishing its task.")

    def stopStorageTraffic(self):
        if self.checkStorageTraffic():
            xenrt.TEC().logverbose("Stopping storage traffic.")
            self.guest.execguest("killall fillguest")

    def checkNetcatTraffic(self, port):
        if xenrt.command("pgrep -f '[n]c.*%s'" % (port), retval="code") and \
           xenrt.command("pgrep -f '[t]cpserver.*%s'" % (port), retval="code"):
            xenrt.TEC().logverbose("Traffic is not being generated.")
            return False
        else:
            xenrt.TEC().logverbose("Traffic is being generated.")
            return True

    def startNetcatTraffic(self, target, port, pattern):
        if self.checkNetcatTraffic(port):
            self.stopNetcatTraffic(port)
        subprocess.Popen("%s/utils/nclisten.sh %s &> /dev/null" % (xenrt.TEC().lookup("LOCAL_SCRIPTDIR"), port), shell=True)
        xenrt.TEC().logverbose("Starting to generate traffic.")
        self.startAsync(target, "while [ 1 ]; do echo %s; done | telnet %s %s &> /dev/null" %
                                (self.ascii(pattern), 
                                 xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"),
                                 port))

    def stopNetcatTraffic(self, port):
        pid = xenrt.command("pgrep -f '[n]c.*%s' || true" % (port)).strip()
        if not pid:
            pid = xenrt.command("pgrep -f '[t]cpserver.*%s'" % (port)).strip()
        xenrt.command("kill %s" % (pid))
        xenrt.TEC().logverbose("Stopping traffic generation.")

    def checkGuestTraffic(self):
        xenrt.TEC().logverbose("Checking if guest traffic is being generated.")
        return self.checkNetcatTraffic(self.GUEST_PORT)

    def startGuestTraffic(self):
        xenrt.TEC().logverbose("Starting guest traffic.")
        self.startNetcatTraffic(self.guest, self.GUEST_PORT, self.GUEST_PATTERN)

    def stopGuestTraffic(self):
        xenrt.TEC().logverbose("Stopping guest traffic.")
        self.stopNetcatTraffic(self.GUEST_PORT)

    def checkManagementTraffic(self):
        xenrt.TEC().logverbose("Checking if management traffic is being generated.")
        return self.checkNetcatTraffic(self.MANAGEMENT_PORT)

    def startManagementTraffic(self):
        xenrt.TEC().logverbose("Starting management traffic.")
        self.startNetcatTraffic(self.host, self.MANAGEMENT_PORT, self.MANAGEMENT_PATTERN)

    def stopManagementTraffic(self):
        xenrt.TEC().logverbose("Stopping management traffic.")
        self.stopNetcatTraffic(self.MANAGEMENT_PORT)

    def checkForPattern(self, bridge, pattern):
        data = self.host.execdom0("tcpdump -i %s -x -c 1024" % (bridge))
        raw = re.sub("\s+", "", string.join(re.findall("0x\d{4}:\s+(.*)", data)))
        return len(re.findall(pattern.strip("0x").lower(), raw))        

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        if isinstance(self.host, xenrt.lib.xenserver.TampaHost):
            self.guest = self.host.createBasicGuest(distro="debian60")
        else:
            self.guest = self.host.createBasicGuest(distro="debian50")
        self.guest.execguest("apt-get install telnet -y --force-yes")
        self.uninstallOnCleanup(self.guest)
        self.installUtilInGuest(self.guest, "%s/progs" % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), "fill")
        self.host.execdom0("iptables -P INPUT ACCEPT")
        self.host.execdom0("iptables -P FORWARD ACCEPT")
        self.host.execdom0("iptables -P OUTPUT ACCEPT")
        self.host.execdom0("iptables -F")
        self.host.execdom0("iptables -X")

    def run(self, arglist):
        self.startStorageTraffic()
        self.startGuestTraffic()
        self.startManagementTraffic()

        if not self.checkForPattern(self.getGuestBridge(self.host), self.GUEST_PATTERN): 
            raise xenrt.XRTFailure("Guest pattern not observed on guest bridge.")
        xenrt.TEC().logverbose("Observed guest pattern on guest bridge")

        if not self.checkForPattern(self.host.getStorageBridge(), self.STORAGE_PATTERN): 
            raise xenrt.XRTFailure("Storage pattern not observed on storage bridge.")
        xenrt.TEC().logverbose("Observed storage pattern on storage bridge")

        if not self.checkForPattern(self.host.getManagementBridge(), self.MANAGEMENT_PATTERN):
            raise xenrt.XRTFailure("Management pattern not observed on management bridge.")
        xenrt.TEC().logverbose("Observed management pattern on management bridge")

        if self.checkForPattern(self.host.getStorageBridge(), self.GUEST_PATTERN):
            raise xenrt.XRTFailure("Guest pattern observed on storage bridge.")
        xenrt.TEC().logverbose("Did not observe guest pattern on storage bridge")

        if self.checkForPattern(self.host.getStorageBridge(), self.MANAGEMENT_PATTERN):
            raise xenrt.XRTFailure("Management pattern observed on storage bridge.")
        xenrt.TEC().logverbose("Did not observe management pattern on storage bridge")

        if self.checkForPattern(self.getGuestBridge(self.host), self.STORAGE_PATTERN):
            raise xenrt.XRTFailure("Storage pattern observed on guest bridge.")
        xenrt.TEC().logverbose("Did not observe storage pattern on guest bridge")

        if self.checkForPattern(self.getGuestBridge(self.host), self.MANAGEMENT_PATTERN):
            raise xenrt.XRTFailure("Management pattern observed on guest bridge.")
        xenrt.TEC().logverbose("Did not observe management pattern on guest bridge")

        if self.checkForPattern(self.host.getManagementBridge(), self.STORAGE_PATTERN):
            raise xenrt.XRTFailure("Storage pattern observed on management bridge.")
        xenrt.TEC().logverbose("Did not observe stoage pattern on management bridge")

        if self.checkForPattern(self.host.getManagementBridge(), self.GUEST_PATTERN):
            raise xenrt.XRTFailure("Guest pattern observed on management bridge.")
        xenrt.TEC().logverbose("Did not observe guest pattern on management bridge")

    def postRun(self):
        try: self.stopStorageTraffic()  
        except: pass
        try: self.stopGuestTraffic()
        except: pass
        try: self.stopManagementTraffic()
        except: pass
        # We cleared the firewall, so lets bring it back
        try: self.host.execdom0("service iptables start")
        except: pass
        _CCSetup.postRun(self)

class _MemorySeparation(_CCSetup):
    """Base class for memory separation test cases."""

    ITERATIONS = 64 
    # We expect to see the pattern 4 times since the memtest code contains it
    # in two locations and they are scanned twice per iteration.
    THRESHOLD = 4 

    def getUsableMemory(self, guest):
        memory_total     = int(self.host.genParamGet("host", 
                                                      self.host.getMyHostUUID(), 
                                                     "memory-total"))
        xenrt.TEC().logverbose("TOTAL: %s" % (memory_total))
        memory_overhead  = int(self.host.genParamGet("host", 
                                                      self.host.getMyHostUUID(), 
                                                     "memory-overhead"))
        xenrt.TEC().logverbose("OVERHEAD: %s" % (memory_overhead))
        vm_memory_total = map(int, (self.host.minimalList("vm-list", 
                                                          "memory-dynamic-max",
                                                          "power-state=running resident-on=%s" %
                                                          (self.host.getMyHostUUID()))))
        xenrt.TEC().logverbose("VM_TOTAL: %s" % (vm_memory_total))
        vm_memory_overhead = map(int, (self.host.minimalList("vm-list", 
                                                             "memory-overhead",
                                                             "power-state=running resident-on=%s" %
                                                             (self.host.getMyHostUUID()))))
        xenrt.TEC().logverbose("VM_OVERHEAD: %s" % (vm_memory_overhead))
        free = (memory_total - \
                memory_overhead - \
                sum(vm_memory_total) - \
                sum(vm_memory_overhead))
        xenrt.TEC().logverbose("FREE: %s" % (free))
        
        upper = free
        lower = (9 * upper) / 10
        while upper - lower > xenrt.MEGA:
            guess = (upper + lower) / 2
            guest.memset(guess/xenrt.MEGA - 1)
            usage = int(self.host.genParamGet("vm", guest.getUUID(), "memory-dynamic-max")) + \
                    int(self.host.genParamGet("vm", guest.getUUID(), "memory-overhead"))        
            if usage < free:
                lower = guess 
            else:
                upper = guess 

        xenrt.TEC().logverbose("RESULT: %s" % (lower))
        return lower/xenrt.MEGA - 1
 
    def getMemtestOutput(self, guest):
        data = self.host.execdom0("sed -ne 's/^.*XenRT return code : \([0-9]\+\) *$/\\1/gp' %s/console.%u.log" %
                                  (self.host.guestconsolelogs, guest.getDomid()))
        return map(int, data.split())

    def iterations(self, guest):
        return len(self.getMemtestOutput(guest))

    def occurrences(self, guest):
        return max(self.getMemtestOutput(guest) + [0])

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        self.host.enableGuestConsoleLogger()
        # Delete any old guest console logs
        self.host.execdom0("rm -f %s/console.*.log" % (self.host.guestconsolelogs))
       
        self.host.execdom0("iptables -P INPUT ACCEPT")
        self.host.execdom0("iptables -P OUTPUT ACCEPT")
        self.host.execdom0("iptables -P FORWARD ACCEPT")
        self.host.execdom0("iptables -F") 
        self.host.execdom0("iptables -X")
        nfs = xenrt.NFSDirectory()
        xenrt.getTestTarball("memtest86+", extract=True, directory=nfs.path())
        xenrt.command("tar xzf %s/memtest86+/memtest86+-4.20.tar.gz -C %s/memtest86+" % 
                      (nfs.path(), nfs.path()))
        xenrt.command("cd %s/memtest86+/memtest86+-4.20 && patch -Np1 < %s/memtest86+/memtest86+-4.20.patch" % 
                      (nfs.path(), nfs.path()))
        xenrt.command("cd %s/memtest86+/memtest86+-4.20 && sh ./make-ci5-isos.sh" % (nfs.path()))
        self.host.createISOSR(nfs.getMountURL("memtest86+/memtest86+-4.20"))
        self.isosr = self.host.parseListForUUID("sr-list",
                                                "name-label",
                                                "Remote ISO Library on: %s" % 
                                                (nfs.getMountURL("memtest86+/memtest86+-4.20")))

        self.reader = self.host.createGenericEmptyGuest(name="reader") 
        self.uninstallOnCleanup(self.reader)
        self.reader.changeCD("reader.iso")

        self.writer = self.host.createGenericEmptyGuest(name="writer")
        self.uninstallOnCleanup(self.writer)
        self.writer.changeCD("writer.iso")

    def postRun(self):
        try: self.reader.shutdown(force=True)
        except: pass
        try: self.writer.shutdown(force=True)
        except: pass
        try: self.host.forgetSR(self.isosr)
        except: pass
        try: self.host.execdom0("service iptables start")
        except: pass
        _CCSetup.postRun(self) 

class TC11224(_MemorySeparation):
    """Memory separation test case."""

    def run(self, arglist):
        self.reader.memset(self.getUsableMemory(self.reader)/2)
        self.reader.start() 
        if xenrt.TEC().lookup("WORKAROUND_CA41286", False, boolean=True):
            self.reader.host.xenstoreWrite("/local/domain/%s/control/feature-balloon" % 
                                           (self.reader.getDomid()), "1")
        self.writer.memset(self.getUsableMemory(self.writer))
        self.writer.start() 
        if xenrt.TEC().lookup("WORKAROUND_CA41286", False, boolean=True):
            self.writer.host.xenstoreWrite("/local/domain/%s/control/feature-balloon" % 
                                           (self.writer.getDomid()), "1")

        while True: 
            if self.occurrences(self.reader) > self.THRESHOLD:
                raise xenrt.XRTFailure("Saw %s occurences of pattern in reading VM." % 
                                       (self.occurrences(self.reader)))
            if self.iterations(self.writer) > self.ITERATIONS:
                break
            time.sleep(5) 

class _RIP(_MemorySeparation):

    ITERATIONS = 1

    def terminate(self):
        raise xenrt.XRTError("Unimplemented.")

    def run(self, arglist):
        self.writer.memset(self.getUsableMemory(self.writer))
        self.writer.start()   

        while self.iterations(self.writer) < self.ITERATIONS: 
            time.sleep(5)

        self.terminate()

        self.reader.memset(self.getUsableMemory(self.reader))
        self.reader.start()  

        while True:
            if self.occurrences(self.reader) > self.THRESHOLD:
                raise xenrt.XRTFailure("Saw %s occurences of pattern in reading VM." % 
                                       (self.occurrences(self.reader)))
            if self.iterations(self.reader) > self.ITERATIONS:
                break
            time.sleep(5) 

class TC11225(_RIP):
    """RIP over VM shutdown."""

    def terminate(self):
        self.writer.shutdown(force=True)
        self.writer.uninstall()

class TC11226(_CCSetup):
    """Check a VDI can't be plugged into two VMs at the same time."""

    def prepare(self, arglist):
        _CCSetup.prepare(self, arglist)
        self.a = self.host.createGenericEmptyGuest()
        self.b = self.host.createGenericEmptyGuest()
        self.uninstallOnCleanup(self.a)
        self.uninstallOnCleanup(self.b)

    def run(self, arglist):
        vbduuid = self.a.createDisk(sizebytes=1, sruuid="DEFAULT", returnVBD=True)
        vdiuuid = self.host.parseListForOtherParam("vbd-list", "uuid", vbduuid, "vdi-uuid")
        
        self.b.createDisk(vdiuuid=vdiuuid, sruuid="DEFAULT")
        self.a.start()
        try:
            self.b.start()
        except xenrt.XRTFailure, e:
            xenrt.TEC().logverbose("Failed as expected: %s" % (str(e)))
        else:
            raise xenrt.XRTFailure("VDI plugged in two VMs.")

class TC11352(_CCSetup):
    """Rejoining a previously failed master to a pool with a new master should fail."""

    def run(self, arglist):
        self.pool.findMaster()
        slave = self.pool.getSlaves()[0]
        oldmaster = self.pool.master
        self.pool.master.execdom0("service xapi stop")
        time.sleep(120)

        self.pool.setMaster(slave)
        self.pool.recoverSlaves()

        if self.pool.master != slave:
            raise xenrt.XRTFailure("Slave did not become the master.")

        oldmaster.reboot()
        oldmaster.waitForXapi(600, desc="Waiting for xapi start after host reboot", local=True)

        # Try to join the old master to the pool.
        # The join should fail.
        success = False
        try:
            self.pool.addHost(oldmaster, bypassSSL=True)
            success = True
        except:
            pass
        if success:
            raise xenrt.XRTFailure("Able to join old master to pool.")

class TC11353(_CCSetup):
    """A host cannot be joined to a pool using an incorrect username or password."""

    def run(self, arglist):
        if len(self.pool.getSlaves()) == 0:
            self.target = self.hosts[1]
        else:
            self.target = self.pool.getSlaves()[0]
            self.pool.eject(self.target)
            self.target.license(edition=self.EDITION, v6server=self.licenseServer)
        self.configureForCC()

        xenrt.TEC().logverbose("Trying to join host to pool with an invalid username.")
        try:
            self.pool.addHost(self.target, user="invalid")
        except: 
            pass
        else:
            raise xenrt.XRTFailure("Host joined pool with invalid username.")

        xenrt.TEC().logverbose("Trying to join host to pool with an invalid password.")
        try:
            self.pool.addHost(self.target, pw="invalid")
        except: 
            pass
        else:
            raise xenrt.XRTFailure("Host joined pool with invalid password.")

    def postRun(self):
        _CCSetup.postRun(self)
        self.pool.addHost(self.target)
        self.target.addIPConfigToNetworkTopology(self.NETWORK)

class TC17223(_MemorySeparation):
    """Verify that any memory returned by an HVM guest is scrubbed when CC restrictions are turned on."""

    def prepare(self, arglist):
        _MemorySeparation.prepare(self, arglist)

        # Set up a 4GB Debian Squeeze VM, to which we'll install our custom kernel
        self.guest = self.host.createBasicGuest(distro="debian60", memory=4096)
        self.uninstallOnCleanup(self.guest)

        # Install the custom kernel
        self.guest.execguest("wget %s/memtest86+.tgz -O /root/memtest86+.tgz" %
                             (xenrt.TEC().lookup("TEST_TARBALL_BASE")))
        self.guest.execguest("tar xvzf /root/memtest86+.tgz -C /root")
        self.guest.execguest("dpkg -i /root/memtest86+/linux/linux-base_2.6.32-48_all.deb")
        self.guest.execguest("dpkg -i /root/memtest86+/linux/linux-image-2.6.32-5-686-bigmem_balloon-pattern.deb")

        # Now fill the hosts memory using a linux VM, minus 256MB
        self.fillGuest = self.host.createBasicGuest(distro="debian60")
        self.fillGuest.shutdown()
        allMemory = self.getUsableMemory(self.fillGuest)
        self.fillGuest.memset(allMemory - 256)

        # Shut down the guest VM so we leave none running
        self.guest.shutdown()
        self.guest.setStaticMemRange(128, 4096)

        # Disable the host firewall (we're liable to reboot the host in this process)
        self.host.execdom0("chkconfig iptables off")

    def checkScrubbing(self):
        """Checks returned memory is scrubbed - returns True if it is"""
        # First remove guest console logs - as we reboot the host in this test domids are reused, and this can cause confusion!
        self.host.execdom0("rm -f %s/console.*.log" % (self.host.guestconsolelogs))

        # Start our various VMs
        self.guest.setDynamicMemRange(4096, 4096)
        self.fillGuest.start()
        self.guest.start()

        # Instruct the guest to return 256MB
        self.guest.setDynamicMemRange(3840, 3840)

        # Now start our reader guest using all available memory and see if it sees the pattern
        self.reader.memset(self.getUsableMemory(self.reader))
        self.reader.start()

        # Wait for at least 1 iteration of the memtest
        while self.iterations(self.reader) < 1:
            time.sleep(5)

        scrubbingOccurred = None
        occurrences = self.occurrences(self.reader)
        xenrt.TEC().logverbose("Found %d occurrences of pattern (threshold %d)" % (occurrences, self.THRESHOLD))
        if occurrences > self.THRESHOLD:
            xenrt.TEC().logverbose("Found pattern in returned memory, scrubbing did not occur")
            scrubbingOccurred = False
        else:
            xenrt.TEC().logverbose("Did not find pattern in returned memory, scrubbing appears to have occurred")
            scrubbingOccurred = True

        self.reader.shutdown(force=True)
        self.guest.shutdown()
        self.fillGuest.shutdown()

        return scrubbingOccurred

    def run(self, arglist):
        xenrt.TEC().progress("Verify returned memory is not scrubbed "
                             "without CC restriction.")
        if self.host.isCCEnabled():
            self.host.disableCC()
        else:
            self.host.reboot() # We want to make sure memory is properly scrubbed before the test

        if self.checkScrubbing():
            raise xenrt.XRTFailure("Guest returned memory appears scrubbed "
                                   "even without CC restriction.")
        else:
            xenrt.TEC().logverbose("Guest returned memory not scrubbed "
                                   "without CC restriction.")

        xenrt.TEC().progress("Verify returned memory is scrubbed "
                             "with CC restriction.")
        self.host.enableCC() # We know this will cause a reboot

        if self.checkScrubbing():
            xenrt.TEC().logverbose("Guest returned memory appears scrubbed "
                                   "with CC restrictions.")
        else:
            raise xenrt.XRTFailure("Guest returned memory not scrubbed "
                                   "even with CC restrictions.")

    def postRun(self):
        _MemorySeparation.postRun(self)
        try: self.host.execdom0("chkconfig iptables on")
        except: pass

class TC17353(_CCSetup):
    """Verify that SSLv2/3 is disabled and only TLSv1 is allowed"""

    def testMode(self, mode, expectedToWork):
        xenrt.TEC().logverbose("Testing SSL mode %s" % (mode))

        rc = xenrt.command("curl -k --%s https://%s" % (mode, self.host.getIP()),
                           retval="code")

        if expectedToWork:
            if rc != 0:
                raise xenrt.XRTFailure("SSL mode %s fails when expected to work" % (mode))
            xenrt.TEC().logverbose("SSL mode %s works as expected" % (mode))
        else:
            if rc == 0:
                raise xenrt.XRTFailure("SSL mode %s works when expected to fail" % (mode))
            if rc != 35:
                raise xenrt.XRTError("SSL mode %s failed as expected but with "
                                     "unexpected return code (%d)" % (rc))
            xenrt.TEC().logverbose("SSL mode %s fails as expected" % (mode))

    def run(self, arglist):

        # Define the modes we are going to test, and whether we expect them to work
        modes = [("sslv2", False),
                 ("sslv3", False),
                 ("tlsv1", True)]

        for mode in modes:
            self.runSubcase("testMode", mode, "SSL", mode[0])

class TC17492(_CCSetup):
    """Verify that linux bridge is in use"""

    def run(self, arglist):

        if self.host.special['Network subsystem type'] == "vswitch":
            raise xenrt.XRTFailure("vswitch is in use")
        elif self.host.special['Network subsystem type'] != "linux":
            raise xenrt.XRTFailure("Unknown network subsystem type %s is in use" %
                                   (self.host.special['Network subsystem type']))

