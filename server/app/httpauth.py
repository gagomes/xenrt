import base64
import kerberos
import os
import config
from pyramid.httpexceptions import HTTPUnauthorized

class HTTPAuth(object):
    def __init__(self, authHeader, page):
        self.page = page
        if authHeader:
            (self.authType, self.authToken) = authHeader.split(" ", 1)
        else:
            self.authType = None
            self.authToken = None
        self.user = None

    def getUser(self):
        if self.authType == "Basic":
            try:
                self._doBasicAuth()
            except Exception, e:
                print e
                self.user = None
        elif self.authType == "Negotiate":
            try:
                self._doNegotiateAuth()
            except Exception, e:
                print e
                self.user = None
        return self.user

    def _doNegotiateAuth(self):
        _ignore_result, context = kerberos.authGSSServerInit("")
        try:
            self._getKerberosDetails()
            kerberos.authGSSServerStep(context, self.authToken)
            targetName = kerberos.authGSSServerTargetName(context)
            if targetName.lower() != self._kerberosPrincipal.lower():
                raise Exception("Target name did not match local principal - %s vs %s" % (targetName, self._kerberosPrincipal))
            response = kerberos.authGSSServerResponse(context)
            principal = kerberos.authGSSServerUserName(context)
            (user, realm) = principal.split("@", 1)
            if realm.lower() != self._kerberosRealm.lower():
                raise Exception("Mismatched realms - %s vs %s" % (realm, self._kerberosRealm))
            self.user = user
            self.page.responseHeaders.append(("WWW-Authenticate", "Negotiate %s" % response))
            print "Did negotiate auth for %s" % self.user
        except:
            print "Failed negotiate auth"
            self.page.offerNegotiate = False
            raise
        finally:
            kerberos.authGSSServerClean(context)


    def _doBasicAuth(self):
        # Future improvement - we could also support LDAP authentication if we wanted to
        # If we're trying basic, that means that negotiate auth has already failed, so don't offer it again
        self.page.offerNegotiate = False
        self._getKerberosDetails()
        (user, password) = base64.b64decode(self.authToken).split(":", 1)
        try:
            kerberos.checkPassword(user, password, self._kerberosService, self._kerberosRealm)
            self.user = user
            print "Authenticated user %s" % user
        except:
            print "Failed to authenticate user %s" % user
            raise

    def _getKerberosDetails(self):
        self._kerberosPrincipal = kerberos.getServerPrincipalDetails("HTTP", config.kerberos_hostname)
        (self._kerberosServiceType, split1) = self._kerberosPrincipal.split("/", 1)
        (self._kerberosService, self._kerberosRealm) = split1.split("@", 1)
