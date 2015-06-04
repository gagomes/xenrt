from server import PageFactory
from app.api import XenRTAPIPage

import app.utils

import string, shutil, traceback, mimetypes
from pyramid.httpexceptions import HTTPFound, HTTPNotFound, HTTPInternalServerError

class XenRTDownload(XenRTAPIPage):
    def render(self):
        form = self.request.params
        if not form.has_key("id"):
            return "ERROR No job specified"
        id = string.atoi(form["id"])
        if form.has_key("prefix"):
            prefix = form["prefix"]
            prefix = string.replace(prefix, '<', '')
            prefix = string.replace(prefix, '>', '')
            prefix = string.replace(prefix, '/', '')
            prefix = string.replace(prefix, '&', '')
            prefix = string.replace(prefix, '\\', '')
        elif form.has_key("phase") and form.has_key("test"):
            id = self.lookup_detailid(id, form["phase"], form["test"])
            if id == -1:
                return "ERROR Specified test not found"
            prefix = "test"
        else:
            prefix = ""

        try:
            filename = app.utils.results_filename(prefix, id)
            self.request.response.body_file = file(filename, "r")
            self.request.response.content_type="application/octet-stream"
            self.request.response.content_disposition = "attachment; filename=\"%d.tar.bz2\"" % (id)
            return self.request.response
        except Exception, e:
            if isinstance(e, IOError):
                # We can still report error to client at this point
                return "ERROR File missing"
            else:
                return "ERROR Internal error"

class XenRTJobFileDownload(XenRTAPIPage):
    def render(self):
        prejob = self.request.params.get("prejob") in ("yes", "true")

        details = self.get_job(self.request.matchdict['job'])
        if prejob:
            server = details['JOB_FILES_SERVER']
        else:
            server = details['LOG_SERVER']

        if server != self.request.host:
            return HTTPFound(location="http://%s%s" % (server, self.request.path_qs))

        filename = self.request.matchdict['filename']
        (ctype, encoding) = mimetypes.guess_type(filename)
        if not ctype:
            ctype = "application/octet-stream"
        
        try:
            localfilename = app.utils.results_filename(filename, int(self.request.matchdict['job']))
            self.request.response.body_file = file(localfilename, "r")
            self.request.response.content_type=ctype
            if encoding:
                self.request.response.content_encoding=encoding
            return self.request.response
        except Exception, e:
            if isinstance(e, IOError):
                return HTTPNotFound()
            else:
                return HTTPInternalServerError()

PageFactory(XenRTDownload, "/api/files/download", compatAction="download")
PageFactory(XenRTJobFileDownload, "/api/getjobfile/{job}/{filename}")
