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

class XenRTUpload(XenRTAPIPage):
    WRITE = True

    def render(self):
        form = self.request.params
        prefix = ""
        phase = None
        test = None
        if form.has_key("phase"):
            phase = form["phase"]
        if form.has_key("test"):
            test = form["test"]
        if form.has_key("prefix"):
            prefix = form["prefix"]
            prefix = string.replace(prefix, '<', '')
            prefix = string.replace(prefix, '>', '')
            prefix = string.replace(prefix, '/', '')
            prefix = string.replace(prefix, '&', '')
            prefix = string.replace(prefix, '\\', '')
        if not form.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(form["id"])

        # See if this is for a particular test
        if phase and test:
            detailid = self.lookup_detailid(id, phase, test)
            if detailid == -1:
                return "ERROR Could not find detailID for %u %s %s" % \
                      (id, phase, test)
            id = detailid
            prefix = "test"

        if not self.request.params.has_key("file"):
            return "ERROR No file supplied"
        fh = None
        data = None
        try:
            fh = self.request.POST["file"].file
        except:
            data = self.request.params["file"]
        try:
            filename = app.utils.results_filename(prefix, id, mkdir=1)
            fout = file(filename, 'w')
            if fh:
                shutil.copyfileobj(fh, fout)
            else:
                fout.write(data)
            fout.close()
        except:
            traceback.print_exc()
            return "ERROR Internal error"

        if phase and test:
            self.update_detailid_uploaded(id, "yes")
       
        return "OK"

    def update_detailid_uploaded(self, detailid, uploaded):
        db = self.getDB()
        cur = db.cursor()

        cur.execute("UPDATE tblResults SET uploaded = %s WHERE detailid = %s",
                    [uploaded, detailid])

        db.commit()

        cur.close()

PageFactory(XenRTDownload, "/api/files/download", compatAction="download")
PageFactory(XenRTJobFileDownload, "/api/getjobfile/{job}/{filename}")
PageFactory(XenRTUpload, "/api/files/upload", compatAction="upload")
