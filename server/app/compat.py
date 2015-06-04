from server import PageFactory
from app import XenRTPage
from pyramid.httpexceptions import HTTPFound

import server

import app.api

class XenRTCompat(XenRTPage):
    def render(self):
        form = self.request.params
        try:
            action = self.request.params['action']
        except:
            return "ERROR: No action specified\n"
       
        compat = server.ServerInstance().getCompatAction(action)

        if compat:
            return compat(self.request).renderWrapper()
        elif action == "frame":
            querystr = self.queryStrFromParams(['jobs', 'detailid'])
            if len(querystr) > 0:
                querystr="?%s" % querystr
            return HTTPFound(location="frame%s" % querystr)
        elif action == "detail":
            querystr = self.queryStrFromParams(['detailid'])
            if len(querystr) > 0:
                querystr="?%s" % querystr
            return HTTPFound(location="detailframe%s" % querystr)
        elif action == "testlogs":
            return HTTPFound(location="logs/job/%s/%s/%s/browse" % (self.request.params['id'], self.request.params['phase'], self.request.params['test']))
        elif action == "browse" or action == "browsebinary" or action == "browsefolded":
            if form.has_key("test") and form['test'] == "yes":
                browsetype = "test"
            else:
                browsetype = "job"
            if form.has_key("filename"):
                if action == "browse":
                    browseformat = "html"
                elif action == "browsebinary":
                    browseformat = "binary"
                elif action == "browsefolded":
                    browseformat = "folded"
                return HTTPFound(location="logs/%s/%s/%s/%s" %
                                    (browsetype,
                                    form['id'],
                                    browseformat,
                                    form['filename']))
            else:
                return HTTPFound(location="logs/%s/%s/browse" %
                                    (browsetype,
                                    form['id']))



        return "ERROR: invalid action specified\n" 

    def queryStrFromParams(self, params):
        retParams = []
        for p in params:
            if self.request.params.has_key(p):
                retParams.append("%s=%s" % (p, self.request.params[p]))
        return "&".join(retParams)

PageFactory(XenRTCompat, "/queue.cgi")
