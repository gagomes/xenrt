from app import XenRTPage
from server import PageFactory
from pyramid.response import FileResponse
import config
import urlparse

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
            "info": {"version": "1.0.0", "title": "XenRT API"},
            "basePath": "%s/api/v2" % u.path.rstrip("/"),
            "host": u.netloc,
            "schemes": [u.scheme],
            "consumes": ["application/json"],
            "produces": ["application/json"],
            "paths": {},
            "security": {"Basic": {}},
            "securityDefinitions": {"Basic": {"type": "basic"}},
            "tags": [
                {"name": "jobs", "description": "Operations on XenRT jobs"}
            ]
        }
        global _apiReg
        for cls in _apiReg.apis:
            if not cls.PATH in spec['paths']:
                spec['paths'][cls.PATH] = {}
            spec['paths'][cls.PATH][cls.REQTYPE.lower()] = {
                "description": cls.DESCRIPTION,
                "tags": cls.TAGS,
                "parameters": cls.PARAMS,
                "responses": cls.RESPONSES
            }
        return spec

PageFactory(XenRTAPIv2Swagger, "/swagger.json", reqType="GET", contentType="application/json")

class XenRTAPIv2Page(XenRTPage):
    REQUIRE_AUTH_IF_ENABLED = True
    PRODUCES = "application/json"
    CONSUMES = "application/json"
    
    def getMultiParam(self, paramName, delimiter=","):
        params = self.request.params.getall(paramName)
        ret = []
        for p in params:
            ret.extend(p.split(delimiter))
        return ret

    pass


import app.apiv2.jobs
