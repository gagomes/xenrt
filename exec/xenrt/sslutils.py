#
# XenRT: Test harness for Xen and the XenServer product family
#
# SSL Certificate Authority functions
#

import sys, os, string, time, random, re
import xenrt

class CertificateAuthority(object):

    # Configuration template uwed with OpenSSL
    CONFIGURATION = """
HOME                    = %(location)s
RANDFILE                = %(random)s

[ ca ]
default_ca      = CA_default

[ CA_default ]
dir              = %(location)s               
database         = %(index)s               
serial           = %(serial)s              
certificate      = %(certificate)s         
private_key      = %(privatekey)s                 
RANDFILE         = %(random)s                 
email_in_dn      = no                      
name_opt         = ca_default              
cert_opt         = ca_default              
copy_extensions  = copy                    
default_enddate  = %(expiry)s          
default_crl_days = 30                   
default_md       = sha1                  
policy           = policy_any              
default_days     = 365

[ req ]
default_bits            = 2048
default_keyfile         = %(privatekey)s
default_md              = sha1
prompt                  = no
req_extensions          = v3_req            
distinguished_name      = req_distinguished_name

[ req_distinguished_name ]
commonName = %(cn)s
countryName = UK
stateOrProvinceName = Cambridgeshire
localityName = Cambridge
organizationName = xensource.com
emailAddress = qa@xensource.com

[ policy_any ]
countryName            = optional
stateOrProvinceName    = optional
organizationName       = optional
organizationalUnitName = optional
commonName             = optional
emailAddress           = optional

[ v3_req ]
subjectAltName         = @alt_names

[ alt_names ]
%(sanlist)s
"""

    def _createConfiguration(self, path, cn, sanlist=[], expired=False):
        xenrt.TEC().logverbose("Expired is: %s" % (expired))
        if sanlist:
            sanlist = string.join(map(lambda x:"DNS.%i = %s" % (x+1, sanlist[x]),
                                        range(len(sanlist))), "\n")
            template = self.CONFIGURATION
        else:
            template = re.sub("req_extensions\s+=\s+v3_req", "", self.CONFIGURATION)
            template = re.sub(".*v3_req.*", "", template)
            template = re.sub(".*subjectAltName.*", "", template)

        if expired:
            expiry = time.strftime("%y%m%d%H%M%SZ",
                                    time.gmtime(time.time() - 60*60*24*365))
        else:
            expiry = time.strftime("%y%m%d%H%M%SZ",
                                    time.gmtime(time.time() + 60*60*24*365))

        configuration = template % {"location"    : self.location,
                                    "index"       : self.index,
                                    "serial"      : self.serial,
                                    "certificate" : self.certificate,
                                    "privatekey"  : self.privatekey,
                                    "random"      : self.random,
                                    "cn"          : cn,
                                    "expiry"      : expiry,
                                    "sanlist"     : sanlist}
        file(path, "w").write(configuration)

    def __init__(self, expired=False):
        try: xenrt.command("which openssl")
        except: raise xenrt.XRTError("OpenSSL must be present on the controller.")

        self.expired = expired

        self._directory = xenrt.resources.TempDirectory()
        self.location = self._directory.path()
        self.configuration  = self.location + "/ca-ssl.conf"
        self.privatekey     = self.location + "/ca-key.pem"
        self.certificate    = self.location + "/ca-cert.pem"
        self.random         = self.location + "/.rnd"
        self.serial         = self.location + "/serial"
        self.index          = self.location + "/index"
        self.issuedCertificates = {}

        self._createConfiguration(self.configuration, "CA", expired=self.expired)
        xenrt.command("openssl req -nodes -config %s -x509 -newkey rsa:2048 "
                      "-out %s -outform PEM -keyout %s -outform PEM" %
                     (self.configuration, self.certificate, self.privatekey))
        xenrt.command("touch %s" % (self.index))
        xenrt.command("echo '01' > %s" % (self.serial))

    def createHostPEM(self, host, cn=None, sanlist=[], expired=False):
        return self.createPEM(host.getName(), host.password, cn, sanlist, expired)

    def createPEM(self, hostname, password, cn=None, sanlist=[], expired=False):
        if self.issuedCertificates.has_key((cn,",".join(sanlist))):
            xenrt.TEC().logverbose("Returning existing certiicate")
            return self.issuedCertificates[(cn,",".join(sanlist))]
        path        = self.location + "/%s-ssl.conf" % (hostname)
        privatekey  = self.location + "/%s-key.pem" % (hostname)
        request     = self.location + "/%s-csr.pem" % (hostname)
        certificate = self.location + "/%s-cert.pem" % (hostname)
        pem         = self.location + "/%s.pem" % (hostname)

        self._createConfiguration(path, cn, sanlist, expired)

        xenrt.TEC().logverbose("Creating PEM for %s with SANs %s and CN %s." %
                               (hostname, sanlist, cn))

        xenrt.command("openssl req -batch -config %s -passout pass:%s "
                      "-newkey rsa:2048 -keyout %s -keyform PEM -out %s "
                      "-outform PEM" %
                      (path, password, privatekey, request))
        xenrt.command("openssl ca -batch -config %s -in %s -outdir %s "
                      "-out %s" %
                      (path, request, self.location, certificate))
        xenrt.command("openssl rsa -passin pass:%s -in %s -out %s" %
                      (password, privatekey, pem))
        xenrt.command("openssl x509 -in %s >> %s" % (certificate, pem))
        self.issuedCertificates[(cn,",".join(sanlist))] = pem
        return pem

