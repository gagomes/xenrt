#!/usr/bin/python

from pyramid.config import Configurator
from pyramid.response import Response
from pyramid.renderers import render_to_response

import config

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
        self.compatActions = {}

    def addPage(self, name, location, function, renderer):
        self.appconfig.add_route(name, location)
        self.appconfig.add_view(function, route_name=name, renderer=renderer)
    
    def getApp(self):
        ### Add code to add static locations here ###
        self.appconfig.add_static_view(name='static', path='__main__:static')
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
    def __init__(self, page, name, location, renderer="string", contentType=None, compatAction=None):
        self.server = ServerInstance()
        self.server.addPage(name, location, self, renderer)
        self.page = page
        self.contentType = contentType
        if renderer == "string":
            self.string = True
            if not self.contentType:
                self.contentType = "text/plain"
        else:
            self.string = False
        if compatAction:
            self.server.addCompatAction(compatAction, page)

    def __call__(self, context, request):
        page = self.page(request)
        ret = page.renderWrapper()
        if self.contentType:
            request.response.content_type = self.contentType
        if self.string and ret and isinstance(ret, basestring) and not ret[-1] == "\n":
            ret += "\n"
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
