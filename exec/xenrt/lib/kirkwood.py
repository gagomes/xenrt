#
# XenRT: Test harness for Xen and the XenServer product family
#
# 'Fake' and Proxy Kirkwood Daemon
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions as
# licensed by Citrix Systems, Inc. All other rights reserved.
#

import threading, BaseHTTPServer, xml.dom.minidom, types, urllib, time, base64
import random, socket, httplib
import SocketServer, tlslite.api, sys, xml.sax.saxutils
import xenrt

# Symbols we want to export from the package.
__all__ = ["FakeKirkwood",
           "ProxyKirkwood",
           "createFakeKirkwood",
           "createProxyKirkwood"]

class KirkwoodHttpException(Exception):
    pass
class KirkwoodMethodException(Exception):
    pass
class KirkwoodAccessException(Exception):
    pass

class KirkwoodHTTPHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    server_version = "FakeKirkwood/1.0"

    @xenrt.irregularName
    def do_GET(self):
        # Get the FakeKirkwood instance
        k = self.server.FakeKirkwood

        # Only get request we should receive is a shutdown
        if self.path != "/shutdown/request":
            k.logError("GET request received to %s" % (self.path))
            self.send_error(400, "Unexpected GET request")
            return

    @xenrt.irregularName
    def do_POST(self):
        # Get the FakeKirkwood instance
        k = self.server.FakeKirkwood

        # Initial sanity checks before attempting to parse request
        #   Verify request was received to the correct path
        if self.path != "/Citrix.Dwm.WorkloadBalance/Service":
            k.logError("Incorrect path used, expecting "
                       "'/Citrix.Dwm.WorkloadBalance/Service', found '%s'" %
                       (self.path))
            # Return an error
            self.send_error(404, "The specified path %s is not a valid Kirkwood"
                                 " path" % (self.path))
            return

        #  Check we have a content-length header
        if not self.headers.has_key("content-length"):
            k.logError("No content-length header found")
            self.send_error(400, "You must specify the content-length header")
            return

        # Retrieve the username and password details from the header
        auth = None
        if self.headers.has_key("Authorization"):
            rawAuth = self.headers["Authorization"]
            if rawAuth.split()[0] == "Basic":
                authDetails = base64.decodestring(rawAuth.split()[1].strip())
                auth = authDetails.split(":")
            else:
                k.logError("Unsupported authentication method %s" %
                           (rawAuth.split()[0]))
                self.send_error(403, "Unsupported auth method %s" %
                                     (rawAuth.split()[0]))
                return

        # Try and parse the body
        body = self.rfile.read(int(self.headers["content-length"]))
        # sys.stderr.write(body)
        d = xml.dom.minidom.parseString(body)
        docElement = d.documentElement

        # Find the body node
        bodyNode = None
        for n in docElement.childNodes:
            if n.localName == "Body":
                bodyNode = n
                break
        if not bodyNode:
            k.logError("Couldn't find Body element in received XML", data=body)
            self.send_error(400, "No Body element found in received XML")
            return

        # Now find the actual method
        method = None
        for n in bodyNode.childNodes:
            if n.localName:
                method = n
                break
        if not method:
            k.logError("Couldn't find method in received XML", data=body)
            self.send_error(400, "Couldn't find method in received XML")
            return

        # Finally find the request object
        request = None
        for n in method.childNodes:
            if n.localName == "request":
                request = n
                break
        if not request:
            k.logError("Couldn't find request in received XML", data=body)
            self.send_error(400, "Couldn't find request in received XML")
            return

        # Now extract the parameters of this request
        params = {}
        for n in request.childNodes:
            if n.localName:
                attrs = n.attributes
                paramDict = None
                if n.localName == "ReportParms":
                    # These require special handling
                    paramDict = {}
                    for cn in n.childNodes:
                        if cn.localName == "ReportParameter":
                            name = None
                            value = None
                            for ccn in cn.childNodes:
                                if ccn.localName == "ParameterName":
                                    if ccn.firstChild:
                                        name = ccn.firstChild.data
                                elif ccn.localName == "ParameterValue":
                                    if ccn.firstChild:
                                        value = ccn.firstChild.data
                            paramDict[name] = value
                # See if this has a namespace associated with it
                for i in range(attrs.length):
                    a = attrs.item(i)
                    if a.prefix == "xmlns":
                        # See if it's an array
                        if a.nodeValue == "http://schemas.microsoft.com/2003/10/Serialization/Arrays":
                            # Yep - handle it as such
                            paramDict = {}
                            for cn in n.childNodes:
                                if cn.localName == "KeyValueOfstringstring":
                                    key = None
                                    value = None
                                    for ccn in cn.childNodes:
                                        if ccn.localName == "Key":
                                            key = ccn.firstChild.data
                                        elif ccn.localName == "Value":
                                            value = ccn.firstChild.data
                                    paramDict[key] = value
                            break
                if type(paramDict) == types.DictType:
                    params[n.localName] = paramDict
                else:
                    # Nothing special, just a normal value                
                    params[n.localName] = n.firstChild.data

        reply = None
        rawrequest = (self.command, self.path, body, self.headers)
        try:
            reply = k.fromXapi(method.localName, rawrequest, params, auth)
        except KirkwoodHttpException, (status, reason):
            self.send_error(status, reason)
            return
        except KirkwoodMethodException:
            self.send_error(400, "Unknown Method %s" % (method.localName))
            return
        except KirkwoodAccessException:
            self.send_error(403, "Forbidden")
            return
        
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        xenrt.TEC().logverbose("Kirkwood reply length %d bytes" % (len(reply)))
        # sys.stderr.write(str(len(reply)))
        badLengths = [1675,1835]
        if (len(reply) - 27) % 32 == 0 or len(reply) in badLengths:
            # Work round a strange bug in the tlslite library, by padding the
            # response with an extra null byte (XRT-5022)
            # Known bad lengths: 955, 1211, 1243, 1675
            # Majority seem to be a multiple of 32 characters (with a 27 char
            # header)
            reply += chr(0)

        self.wfile.write(reply)        

class KirkwoodHTTPServer(SocketServer.ThreadingMixIn,
                         tlslite.api.TLSSocketServerMixIn,
                         BaseHTTPServer.HTTPServer):
    def __init__(self, ip, port, fk, cert, key):
        self.FakeKirkwood = fk

        if not cert:
            # Use a dummy self signed certificate
            cert = """-----BEGIN CERTIFICATE-----
MIID7zCCA1igAwIBAgIJAMp0CCkS1yJcMA0GCSqGSIb3DQEBBQUAMIGsMQswCQYD
VQQGEwJHQjEXMBUGA1UECBMOQ2FtYnJpZGdlc2hpcmUxEjAQBgNVBAcTCUNhbWJy
aWRnZTEhMB8GA1UECgwYQ2l0cml4IFN5c3RlbXMgKFImRCkgTHRkMRUwEwYDVQQL
EwxYZW5TZXJ2ZXIgUUExFTATBgNVBAMTDEZha2VLaXJrd29vZDEfMB0GCSqGSIb3
DQEJARYQcWFAeGVuc291cmNlLmNvbTAeFw0wOTAxMDYxODI4MDlaFw0zNjA1MjQx
ODI4MDlaMIGsMQswCQYDVQQGEwJHQjEXMBUGA1UECBMOQ2FtYnJpZGdlc2hpcmUx
EjAQBgNVBAcTCUNhbWJyaWRnZTEhMB8GA1UECgwYQ2l0cml4IFN5c3RlbXMgKFIm
RCkgTHRkMRUwEwYDVQQLEwxYZW5TZXJ2ZXIgUUExFTATBgNVBAMTDEZha2VLaXJr
d29vZDEfMB0GCSqGSIb3DQEJARYQcWFAeGVuc291cmNlLmNvbTCBnzANBgkqhkiG
9w0BAQEFAAOBjQAwgYkCgYEAwJiGIX5IHQwXXHO4d+6WzKCe/mgmxZMG3BD1Rj6v
oNnsE1jgk5REuslo7KmJu62Bhiq3CSakZNIZgFx0Z7qOitTwHX+OCNzcVWtA4VFI
ItlPnjcOa6dnMZsvCpkAsWWxEohGlNCyVy/Go66JNAkajH6YHs2MetHoYDXwQCQS
8CkCAwEAAaOCARUwggERMB0GA1UdDgQWBBQ1SpzMrf0H+Via4nIVwO1fRUFNLjCB
4QYDVR0jBIHZMIHWgBQ1SpzMrf0H+Via4nIVwO1fRUFNLqGBsqSBrzCBrDELMAkG
A1UEBhMCR0IxFzAVBgNVBAgTDkNhbWJyaWRnZXNoaXJlMRIwEAYDVQQHEwlDYW1i
cmlkZ2UxITAfBgNVBAoMGENpdHJpeCBTeXN0ZW1zIChSJkQpIEx0ZDEVMBMGA1UE
CxMMWGVuU2VydmVyIFFBMRUwEwYDVQQDEwxGYWtlS2lya3dvb2QxHzAdBgkqhkiG
9w0BCQEWEHFhQHhlbnNvdXJjZS5jb22CCQDKdAgpEtciXDAMBgNVHRMEBTADAQH/
MA0GCSqGSIb3DQEBBQUAA4GBAHFUaMH9LNMr8CzQp4/EYTrzRW9mbMhn/e07b8lg
MQI/RdbeGVB6qhelwOOyKcOvvin6eCqrfHIsBdhUVJWhuqHh96oKeRyon1G+st7G
53Byyf2JvunR2HAc84s58zfJZoM7CIuEF2bd8unq1RKOjVxL9TSMbes3KZQ10kLG
dGY8
-----END CERTIFICATE-----
"""
            key = """-----BEGIN RSA PRIVATE KEY-----
MIICXQIBAAKBgQDAmIYhfkgdDBdcc7h37pbMoJ7+aCbFkwbcEPVGPq+g2ewTWOCT
lES6yWjsqYm7rYGGKrcJJqRk0hmAXHRnuo6K1PAdf44I3NxVa0DhUUgi2U+eNw5r
p2cxmy8KmQCxZbESiEaU0LJXL8ajrok0CRqMfpgezYx60ehgNfBAJBLwKQIDAQAB
AoGBALPoxsNa17pqpRfz8Yn3El8sW9mDKVS+t1Wzcauguyci6uhXydGSW3Gw25bX
+JWcyrWuCTU/J6oWqUPDGeob1zIxfqjsir3AvHbgOi3gizkrumk+4542e3E1ufYI
LDIxxbeQ36YRZ3KHrtuqZmwk7tCYmgiblxR+pY3MecyXe1/RAkEA7B/Cb0lQllQb
YRSxM4WUiuqFbLsoVpTdJz/K0E/3uL5Mz1Xvrn/cwOgMEPcQS1RiTK9ZCPjFw5Tr
IlHiKyRuPwJBANDOxfdhdpNl7BMIhKQR1SXI2ZeKMDjP45xQ4hKlV2HQIETpQZ90
v8j4PJ4lxjnOTeRSC2CFHw/KFIoHEiVB15cCQDxAYmnpSFIDxjTAhfMCrAPCkidL
nqBxPfls8sCzFyAiFxF0+UMKx3bF/4Y4tQSz1J2CxPJgIH6mulU4lcCyfBsCQEZP
mjG2y+rOQzQVhjSJHLDgdQSmL56xwf787WNB8a6qGnOZ59L9ySavEBpgteL5KRlc
1x/lM5Rpg4kG4IFTLnkCQQCcTtnhshul5bcjor9J+oKJQ7q7YIEIzqUbdJgCFfs1
hKIs4YWO6PDU3wwSSCLAmTvFuTj0VOFEfUaWax7tTkrj
-----END RSA PRIVATE KEY-----
"""

        x509 = tlslite.api.X509()
        x509.parse(cert)
        self.certChain = tlslite.api.X509CertChain([x509])
        self.privateKey = tlslite.api.parsePEMKey(key, private=True)
        self.sessionCache = tlslite.api.SessionCache()

        BaseHTTPServer.HTTPServer.__init__(self, (ip,port), KirkwoodHTTPHandler)

    def handshake(self, tlsConnection):
        try:
            settings = tlslite.api.HandshakeSettings()
            settings.minVersion=(3,0)
            tlsConnection.handshakeServer(certChain=self.certChain,
                                          privateKey=self.privateKey,
                                          sessionCache=self.sessionCache,
                                          settings=settings)
            tlsConnection.ignoreAbruptClose = True
            return True
        except tlslite.api.TLSError, error:
            sys.stderr.write("Handshake failure: %s\n" % (str(error)))
            return False

class FakeKirkwood(threading.Thread):
    METHODS = ["AddXenServer",
               "RemoveXenServer",
               "SetXenPoolConfiguration",
               "GetXenPoolConfiguration",
               "VMGetRecommendations",
               "HostGetRecommendations",
               "GetOptimizationRecommendations",
               "ExecuteReport",
               "GetDiagnostics"]

    def __init__(self, ip, port, cert=None, key=None):
        self.ip = ip
        self.port = port
        self.http = KirkwoodHTTPServer(ip, port, self, cert, key)

        self.stop = False

        self.requests = []
        self.errors = []
        self.rqLock = threading.Lock()

        # recommendations contains a dictionary mapping VM uuids to a list of
        # recommendation dictionaries
        self.recommendations = {}
        # hostRecommendations is a dictionary mapping host uuids to a tuple,
        # the first part set True/False/None to specify what to do with the
        # CanPlaceAllVMs field, the second part containing a list of
        # recommendation dictionaries
        self.hostRecommendations = {}        

        # poolConfig contains a dictinoary of data to retrun to the get/set
        # configuration methods
        self.poolConfig = {}

        # optimizations is a tuple containing an optimization id, a list of
        # recommendation dictionaries, and a Severity string
        self.optimizations = None

        # reportXML contains an XML reply to send to *any* ExecuteReport request
        self.reportXML = ""

        # The various things we can return
        self.returnError = None
        self.returnSpecial = None
        self.returnNone = False
        self.returnForbidden = False
        self.delayReply = None

        # Generate a dictionary of error responses
        self.errorResponses = {}
        self._addErrorResponse("InvalidParameter", 4007)

        # Initialise thread functions
        threading.Thread.__init__(self)

        # Make ourself daemonic
        self.setDaemon(True)

    def run(self):
        # Loop until we're stopped handling requests
        while not self.stop:
            self.http.handle_request()

    def shutdown(self):
        if self.isAlive():        
            self.stop = True
            # Open an (invalid) request to ourselves locally, this should cause
            # the thread to shutdown
            try:
                h = tlslite.api.HTTPTLSConnection("%s:%s" %
                                                  (self.http.server_name,
                                                   self.http.server_port))
                h.request("GET", "/shutdown/request")
                h.close()
            except:
                pass
            xenrt.sleep(2)
        # Shut down the server
        self.http.server_close()

    def _addErrorResponse(self, message, code):
        error = """          <ErrorMessage>%s</ErrorMessage>
          <ResultCode>%s</ResultCode>
""" % (message, code)
        self.errorResponses[message] = error

    def logError(self, error, data=None):
        self.rqLock.acquire()
        self.errors.append((error, data))
        self.rqLock.release()

    def fromXapi(self, method, rawrequest, params, auth):
        if method in self.METHODS:
            actualMethod = eval("self." + method[0].lower() + method[1:])
            self.rqLock.acquire()
            self.requests.append((method, params, auth))
            self.rqLock.release()
            if self.returnError:
                return self.generateReplyXML(method,
                                          self.errorResponses[self.returnError])
            elif self.returnSpecial:
                return self.returnSpecial
            elif self.returnNone:
                return None
            elif self.returnForbidden:
                raise KirkwoodAccessException()
            else:
                if self.delayReply:
                    xenrt.sleep(self.delayReply)
                return self.generateReplyXML(method, actualMethod(rawrequest, params))
        else:
            self.logError("Unknown method %s called" % (method), data=params)
            raise KirkwoodMethodException()

    def generateReplyXML(self, method, reply=None):
        data = """  <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://www.w3.org/2005/08/addressing">
    <s:Body>
      <%sResponse xmlns="http://schemas.citrix.com/DWM">
        <%sResult xmlns:i="http://www.w3.org/2001/XMLSchema-instance\"""" % (method, method)
        if reply:
            data += """>
          %s
        </%sResult>""" % (reply, method)
        else:
            data += "/>"
        data += """
      </%sResponse>
    </s:Body>
  </s:Envelope>""" % (method)
        return data

    def addXenServer(self, rawrequest, params):
        return "<Id>1</Id>"

    def removeXenServer(self, rawrequest, params):
        return None

    def setXenPoolConfiguration(self, rawrequest, params):
        return None

    def getXenPoolConfiguration(self, rawrequest, params):
        # Return the pool config
        reply = """          <OptimizationParms xmlns:b="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
"""
        for pc in self.poolConfig:
            reply += """            <b:KeyValueOfstringstring>
              <b:Key>%s</b:Key>
              <b:Value>%s</b:Value>
            </b:KeyValueOfstringstring>
""" % (xml.sax.saxutils.escape(pc),xml.sax.saxutils.escape(self.poolConfig[pc]))
        reply += "          </OptimizationParms>\n"
        return reply

    def vMGetRecommendations(self, rawrequest, params):
        if not params.has_key("VmUuid"):
            return self.errorResponses['InvalidParameter']
        if self.recommendations.has_key(params['VmUuid']):
            data = "<Recommendations>"        
            for r in self.recommendations[params['VmUuid']]:
                data += "<VmPlacementRecommendation>\n"
                for kv in r:
                    data += "              <%s>%s</%s>\n" % (kv,r[kv],kv)
                data += "</VmPlacementRecommendation>\n"
            data += "</Recommendations>"
            return data
        else:
            return "<Recommendations/>"

    def hostGetRecommendations(self, rawrequest, params):
        if not params.has_key("HostUuid"):
            return self.errorResponses['InvalidParameter']
        if self.hostRecommendations.has_key(params['HostUuid']):
            if self.hostRecommendations[params['HostUuid']][0]:
                data = "<CanPlaceAllVMs>true</CanPlaceAllVMs>"
            elif type(self.hostRecommendations[params['HostUuid']][0]) == types.BooleanType:
                data = "<CanPlaceAllVMs>false</CanPlaceAllVMs>"
            else:
                data = ""
            data += "<Recommendations>"
            for r in self.hostRecommendations[params['HostUuid']][1]:
                data += "<HostEvacuationRecommendation>\n"
                for kv in r:
                    data += "              <%s>%s</%s>\n" % (kv,r[kv],kv)
                data += "</HostEvacuationRecommendation>\n"
            data += "</Recommendations>"
            return data
        else:
            return "<Recommendations/>"

    def getOptimizationRecommendations(self, rawrequest, params):
        if not self.optimizations:
            return None
        reply = """          <OptimizationId>%d</OptimizationId>
          <Recommendations>
""" % (self.optimizations[0])
        for por in self.optimizations[1]:
            reply += "            <PoolOptimizationRecommendation>\n"
            for p in por:
                reply += "              <%s>%s</%s>\n" % (p,por[p],p)
            reply += "            </PoolOptimizationRecommendation>\n"
        reply += """          </Recommendations>
          <Severity>%s</Severity>
""" % (self.optimizations[2])

        return reply

    def executeReport(self, rawrequest, params):
        reply = """          <XmlDataSet>
%s
          </XmlDataSet>
""" % (xml.sax.saxutils.escape(self.reportXML))
        return reply

    def getDiagnostics(self, rawrequest, params):
        return ""

    # Utility functions
    def resetRequests(self):
        self.rqLock.acquire()
        self.requests = []
        self.rqLock.release()

    def resetErrors(self):
        self.rqLock.acquire()
        self.errors = []
        self.rqLock.release()

    def resetBoth(self):
        self.rqLock.acquire()
        self.requests = []
        self.errors = []
        self.rqLock.release()

    def getRequests(self):
        return self.requests

    def getErrors(self):
        return self.errors



class ProxyKirkwood(FakeKirkwood):

    def __init__(self, vpxwlb_ip, vpxwlb_port, ip, port, cert=None, key=None):
        FakeKirkwood.__init__(self, ip, port, cert, key)
        self.vpxwlb_ip = vpxwlb_ip
        self.vpxwlb_port = vpxwlb_port

    def vpxWlbSendReceive(self, rawrequest):
        cmd, path, body, headers = rawrequest
        headers['Host']=self.vpxwlb_ip
        xenrt.TEC().logverbose("cmd=%s" % cmd)
        xenrt.TEC().logverbose("path=%s" % path)
        xenrt.TEC().logverbose("headers=%s" % headers)
        xenrt.TEC().logverbose("body=%s" % body)
        hconn = httplib.HTTPSConnection(self.vpxwlb_ip, self.vpxwlb_port)
        hs = dict(headers.items())
        hconn.request(cmd, path, body, hs)
        resp = hconn.getresponse()
        if resp.status != 200:
            self.logError("HttpException: %s %s" % (resp.status, resp.reason))
            raise KirkwoodHttpException, (resp.status, resp.reason)
        data = resp.read()
        hconn.close()    
        xenrt.TEC().logverbose("response=%s" % data)
        return data

    def generateReplyXML(self, method, reply=None):
        return reply

    def addXenServer(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def removeXenServer(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def setXenPoolConfiguration(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def getXenPoolConfiguration(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def vMGetRecommendations(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def hostGetRecommendations(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def getOptimizationRecommendations(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def executeReport(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

    def getDiagnostics(self, rawrequest, params):
        return self.vpxWlbSendReceive(rawrequest)

def createFakeKirkwood(port=None,cert=None,key=None):
    # Determine IP and port to use
    # Listen on the controller IP
    ip = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
    # We use a port in the range 30000-40000, randomly chosen

    if port:            
        kirkwood = FakeKirkwood(ip, port, cert, key)
    else:
        kirkwood = None
        tries = 0
        while not kirkwood:
            port = random.randint(30000,40000)
            xenrt.TEC().logverbose("Trying to use port %d" % (port))
            try:
                kirkwood = FakeKirkwood(ip, port, cert, key)
            except socket.error, e:
                if e[0] == 98: # Address already in use - try again
                    xenrt.TEC().logverbose("Port appears to be in use")
                    kirkwood = None
                else:
                    raise e
            tries += 1
            if tries > 5:
                raise xenrt.XRTError("Couldn't find an available port "
                                     "after 5 attempts")

    kirkwood.start()
    return kirkwood

def createProxyKirkwood(vpxwlb_ip,vpxwlb_port,port=None,cert=None,key=None):
    # Determine IP and port to use
    # Listen on the controller IP
    ip = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
    # We use a port in the range 30000-40000, randomly chosen

    if port:            
        kirkwood = ProxyKirkwood(vpxwlb_ip, vpxwlb_port, ip, port, cert, key)
    else:
        kirkwood = None
        tries = 0
        while not kirkwood:
            port = random.randint(30000,40000)
            xenrt.TEC().logverbose("Trying to use port %d" % (port))
            try:
                kirkwood = ProxyKirkwood(vpxwlb_ip, vpxwlb_port, ip, port, cert, key)
            except socket.error, e:
                if e[0] == 98: # Address already in use - try again
                    xenrt.TEC().logverbose("Port appears to be in use")
                    kirkwood = None
                else:
                    raise e
            tries += 1
            if tries > 5:
                raise xenrt.XRTError("Couldn't find an available port "
                                     "after 5 attempts")

    kirkwood.start()
    return kirkwood

