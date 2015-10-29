from app import XenRTPage
from server import PageFactory
from pyramid.response import FileResponse
from pyramid.httpexceptions import *
import config
import urlparse
import json

__all__ = ["XenRTAPIError", "XenRTAPIv2Page", "RegisterAPI"]

def XenRTAPIError(page, errtype, reason, canForce=None):
    ret = {"reason": reason}
    if canForce != None:
        ret['can_force'] = canForce
    return errtype(body=json.dumps(ret, encoding="latin-1"), content_type="application/json", headers = self.page.responseHeaders)

class ApiRegistration(object):
    def __init__(self):
        self.apis = []

    def registerAPI(self, cls):
        self.apis.append(cls)
        if cls.FILEAPI:
            PageFactory(cls, "/api/files/v2%s" % cls.PATH, reqType = cls.REQTYPE, contentType = cls.PRODUCES)
        else:
            PageFactory(cls, "/api/v2%s" % cls.PATH, reqType = cls.REQTYPE, contentType = cls.PRODUCES)


global _apiReg
_apiReg = ApiRegistration()

def RegisterAPI(cls):
    global _apiReg
    _apiReg.registerAPI(cls)

class XenRTAPIv2Swagger(XenRTPage):
    def render(self):
        u = urlparse.urlparse(config.url_base)
        spec = {
            "swagger": "2.0",
            "info": {
                "version": "1.0.0",
                "title": "XenRT API",
                "description": """XenRT API can be authenticated in 3 ways<br />
- Kerberos on the Citrite AD domain<br />
- Basic authentication using Citrite domain credentials<br />
- API Key, by passing your API key (obtain <a href="/xenrt/ui/apikey">here</a>) in the x-api-key HTTP header<br />
<br />
<a href="/xenrtapi.tar.gz">Download python bindings/CLI (install with pip)</a>"""
            },
            "basePath": "%s/api/v2" % u.path.rstrip("/"),
            "uiPath": "%s/ui" % u.path.rstrip("/"),
            "host": u.netloc,
            "masterhost": config.master_server,
            "schemes": [u.scheme],
            "consumes": ["application/json"],
            "produces": ["application/json"],
            "paths": {},
            "security": {"Basic": {}},
            "securityDefinitions": {"Basic": {"type": "basic"}},
            "tags": [
                {"name": "jobs", "description": "Operations on XenRT jobs"},
                {"name": "machines", "description": "Operations on XenRT machines"},
                {"name": "sites", "description": "Operations on XenRT sites"},
                {"name": "apikeys", "description": "Operations on XenRT API keys"},
                {"name": "backend", "description": "Operations used by XenRT controllers, not for general use"},
                {"name": "acls", "description": "Operations on XenRT Access Control Lists"},
                {"name": "suiterun", "description": "Operations to start suiteruns"},
                {"name": "misc", "description": "Miscellaneous operations"}
            ],
            "definitions": {}
        }
        global _apiReg
        for cls in _apiReg.apis:
            if cls.HIDDEN or cls.FILEAPI:
                continue
            if not cls.PATH in spec['paths']:
                spec['paths'][cls.PATH] = {}
            spec['paths'][cls.PATH][cls.REQTYPE.lower()] = {
                "summary": cls.SUMMARY,
                "tags": cls.TAGS,
                "parameters": cls.PARAMS,
                "responses": cls.RESPONSES,
                "consumes": [cls.CONSUMES],
                "produces": [cls.PRODUCES]
            }
            if cls.DESCRIPTION:
                spec['paths'][cls.PATH][cls.REQTYPE.lower()]['description'] = cls.DESCRIPTION
            if cls.PARAM_ORDER:
                spec['paths'][cls.PATH][cls.REQTYPE.lower()]['paramOrder'] = cls.PARAM_ORDER
            if cls.RETURN_KEY:
                spec['paths'][cls.PATH][cls.REQTYPE.lower()]['returnKey'] = cls.RETURN_KEY
            if cls.OPERATION_ID:
                spec['paths'][cls.PATH][cls.REQTYPE.lower()]['operationId'] = cls.OPERATION_ID
            if cls.MASTER_ONLY:
                spec['paths'][cls.PATH][cls.REQTYPE.lower()]['masterOnly'] = True
            spec['definitions'].update(cls.DEFINITIONS)
        return spec

PageFactory(XenRTAPIv2Swagger, "/swagger.json", reqType="GET", contentType="application/json")

class XenRTAPIv2Page(XenRTPage):
    REQUIRE_AUTH_IF_ENABLED = True
    DESCRIPTION = None
    PRODUCES = "application/json"
    CONSUMES = "application/json"
    DEFINITIONS = {}
    OPERATION_ID = None
    PARAM_ORDER = []
    RETURN_KEY = None
    HIDDEN = False
    FILEAPI = False
    MASTER_ONLY = False

    def getIntFromMatchdict(self, paramName):
        if not paramName in self.request.matchdict:
            raise KeyError("%s not found" % paramName)
        try:
            return int(self.request.matchdict[paramName])
        except ValueError:
            raise XenRTAPIError(self, HTTPBadRequest, "Invalid %s in URL" % paramName)

    def getMultiParam(self, paramName, delimiter=","):
        params = self.request.params.getall(paramName)
        ret = []
        for p in params:
            ret.extend(p.split(delimiter))
        return [x for x in ret if x != '']

    def generateInCondition(self, fieldname, items):
        return "%s IN (%s)" % (fieldname, ", ".join(["%s"] * len(items)))

    def expandVariables(self, params):
        return [self.getUser().userid if x=="${user}" else x for x in params]

import app.apiv2.bindings
import app.apiv2.powershellbindings
import app.apiv2.jobs
import app.apiv2.machines
import app.apiv2.files
import app.apiv2.sites
import app.apiv2.api
import app.apiv2.acls
import app.apiv2.misc
import app.apiv2.resources
import app.apiv2.results
import app.apiv2.suite
