from app import XenRTPage
from server import PageFactory
from pyramid.response import FileResponse
import config
import urlparse
import json

__all__ = ["XenRTAPIError", "XenRTAPIv2Page", "RegisterAPI"]

def XenRTAPIError(errtype, reason, canForce=None):
    ret = {"reason": reason}
    if canForce != None:
        ret['can_force'] = canForce
    return errtype(body=json.dumps(ret))

class ApiRegistration(object):
    def __init__(self):
        self.apis = []

    def registerAPI(self, cls):
        self.apis.append(cls)
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
                "description": "<a href=\"%s://%s%s/bindings/xenrtapi.py\">Python bindings</a>" % (u.scheme, u.netloc, u.path.rstrip("/"))
            },
            "basePath": "%s/api/v2" % u.path.rstrip("/"),
            "host": u.netloc,
            "schemes": [u.scheme],
            "consumes": ["application/json"],
            "produces": ["application/json"],
            "paths": {},
            "security": {"Basic": {}},
            "securityDefinitions": {"Basic": {"type": "basic"}},
            "tags": [
                {"name": "jobs", "description": "Operations on XenRT jobs"},
                {"name": "machines", "description": "Operations on XenRT machines"},
                {"name": "sites", "description": "Operations on XenRT sites"}
            ],
            "definitions": {}
        }
        global _apiReg
        for cls in _apiReg.apis:
            if cls.HIDDEN:
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
            if cls.OPERATION_ID:
                spec['paths'][cls.PATH][cls.REQTYPE.lower()]['operationId'] = cls.OPERATION_ID
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
    HIDDEN = False
    
    def getMultiParam(self, paramName, delimiter=","):
        params = self.request.params.getall(paramName)
        ret = []
        for p in params:
            ret.extend(p.split(delimiter))
        return ret

    def generateInCondition(self, fieldname, items):
        return "%s IN (%s)" % (fieldname, ", ".join(["%s"] * len(items)))

    def expandVariables(self, params):
        return [self.getUser() if x=="${user}" else x for x in params]

import app.apiv2.bindings
import app.apiv2.jobs
import app.apiv2.machines
import app.apiv2.files
import app.apiv2.sites
