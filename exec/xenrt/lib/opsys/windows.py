import xenrt
import string, xmlrpclib, IPy, httplib, socket
from xenrt.lib.opsys import OS, RegisterOS

class MyHTTPConnection(httplib.HTTPConnection):
    XENRT_SOCKET_TIMEOUT = 600
    
    def connect(self):
        """Connect to the host and port specified in __init__."""
        self.timeout =  self.XENRT_SOCKET_TIMEOUT
        self.sock = socket.create_connection((self.host, self.port),
                                             self.timeout)
        if self._tunnel_host:
            self._tunnel()

class MyReallyImpatientHTTPConnection(MyHTTPConnection):
    XENRT_SOCKET_TIMEOUT = 5

class MyImpatientHTTPConnection(MyHTTPConnection):
    XENRT_SOCKET_TIMEOUT = 30

class MyPatientHTTPConnection(MyHTTPConnection):
    XENRT_SOCKET_TIMEOUT = 86400

class MyTrans(xmlrpclib.Transport):

    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host)
        return MyHTTPConnection(host)

class MyReallyImpatientTrans(xmlrpclib.Transport):

    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host)
        return MyReallyImpatientHTTPConnection(host)

class MyImpatientTrans(xmlrpclib.Transport):

    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host) 
        return MyImpatientHTTPConnection(host)

class MyPatientTrans(xmlrpclib.Transport):

    @xenrt.irregularName
    def make_connection(self, host):
        # create a HTTP connection object from a host descriptor
        host, extra_headers, x509 = self.get_host_info(host) 
        return MyPatientHTTPConnection(host)


class WindowsOS(OS):

    @staticmethod
    def KnownDistro(distro):
        if distro[0] == 'w' or distro[0] == 'v':
            return True
        else:
            return False

    def __init__(self, distro, parent):
        super(self.__class__, self).__init__(parent)

        self.distro = distro
        self.isoRepo = "windows"
        self.isoName = "%s.iso" % self.distro
        self.supportedInstallMethods = ["iso"]

    def waitForInstallCompleteAndFirstBoot(self):
        self.parent.getIP(10800)
        self.waitForDaemon(14400)

    def waitForDaemon(self, timeout):
        sleeptime = 15
        now = xenrt.util.timenow()
        deadline = now + timeout
        perrors = 0
        while True:
            xenrt.TEC().logverbose("Checking for exec daemon on %s" %
                                   (self.parent.getIP()))
            try:
                if self._xmlrpc(impatient=True).isAlive():
                    xenrt.TEC().logverbose(" ... OK reply from %s" %
                                           (self.parent.getIP()))
                    return xenrt.RC_OK
            except socket.error, e:
                xenrt.TEC().logverbose(" ... %s" % (str(e)))
            except socket.timeout, e:
                xenrt.TEC().logverbose(" ... %s" % (str(e)))
            except xmlrpclib.ProtocolError, e:
                perrors = perrors + 1
                if perrors >= 3:
                    raise
                xenrt.TEC().warning("XML-RPC daemon ProtocolError during "
                                    "poll (%s)" % (str(e)))
            now = xenrt.util.timenow()
            if now > deadline:
                raise xenrt.XRTFailure("Waiting for XML/RPC timed out")
            xenrt.sleep(sleeptime, log=False)
    
    def _xmlrpc(self, impatient=False, patient=False, reallyImpatient=False):
        if reallyImpatient:
            trans = MyReallyImpatientTrans()
        elif impatient:
            trans = MyImpatientTrans()
        elif patient:
            trans = MyPatientTrans()
        else:
            trans = MyTrans()
            
        ip = IPy.IP(self.parent.getIP())
        url = ""
        if ip.version() == 6:
            url = 'http://[%s]:8936'
        else:
            url = 'http://%s:8936'
        return xmlrpclib.ServerProxy(url % (self.parent.getIP()),
                                     transport=trans, 
                                     allow_none=True)

RegisterOS(WindowsOS)
