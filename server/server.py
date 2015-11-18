#!/usr/bin/python

from pyramid.config import Configurator
from pyramid.response import Response
from pyramid.renderers import render_to_response
from pyramid.httpexceptions import *

import config

import uuid
import json
import traceback
import sys
import gc

#def launch_memory_usage_server(port = 8080):
#    import cherrypy
#    import dowser
#    
#    cherrypy.tree.mount(dowser.Root())
#    cherrypy.config.update({
#        'environment': 'embedded',
#        'server.socket_port': port,
#        'server.socket_host': '0.0.0.0'
#    })
#    print "Starting cherrypy"
#    cherrypy.engine.start()

class Server(object):
    def __init__(self):
        self.appconfig = Configurator()
        self.appconfig.include("pyramid_chameleon")
        self.appconfig.include("pyramid_mako")
        self.compatActions = {}

    def addPage(self, location, function, renderer, reqType):
        name = str(uuid.uuid4())
        self.appconfig.add_route(name, location, request_method=reqType)
        self.appconfig.add_view(function, route_name=name, renderer=renderer)

    def getApp(self):
        ### Add code to add static locations here ###
        self.appconfig.add_static_view(name='static', path='__main__:static')
        self.appconfig.add_static_view(name='swagger', path='__main__:swagger')
        app = self.appconfig.make_wsgi_app()
        return app

    def addCompatAction(self, name, page):
        self.compatActions[name] = page

    def getCompatAction(self, name):
        if self.compatActions.has_key(name):
            return self.compatActions[name]
        else:
            return None

class PageFactory(object):
    def __init__(self, page, location, renderer="string", contentType=None, compatAction=None, reqType=None):
        self.server = ServerInstance()
        self.server.addPage(location, self, renderer, reqType)
        self.page = page
        self.contentType = contentType
        if renderer == "string":
            self.string = True
            if not self.contentType:
                self.contentType = "text/plain"
        else:
            self.string = False
        self.json = self.contentType == "application/json"
        if compatAction:
            self.server.addCompatAction(compatAction, page)

    def __call__(self, context, request):
        page = self.page(request)
        try:
            ret = page.renderWrapper()
        except Exception, e:
            if isinstance(e, HTTPException):
                raise
            else:
                traceback.print_exc(sys.stderr)
                if self.json:
                    raise HTTPInternalServerError(body=json.dumps({"reason": str(e), "traceback": traceback.format_exc()}), content_type="application/json")
                else:
                    raise HTTPInternalServerError(body="Internal Server error:\n\n%s" % traceback.format_exc(), content_type="text/plain")
        request.response.headerlist.extend(page.responseHeaders)
        if request.params.get("plain") == "true":
            request.response.content_type == "text/plain"
        elif self.contentType:
            request.response.content_type = self.contentType
        if self.string and ret and isinstance(ret, basestring) and not ret[-1] == "\n":
            ret += "\n"
        if self.json and ret and not isinstance(ret, basestring) and not isinstance(ret, HTTPException):
            ret = json.dumps(ret, indent=2, sort_keys=True, encoding="latin-1")
        page = None
        gc.collect()
        return ret

class Page(object):
    def __init__(self, request):
        self.request = request

global _server
_server = None

def ServerInstance():
    global _server
    if not _server:
        _server = Server()
    return _server

import app
