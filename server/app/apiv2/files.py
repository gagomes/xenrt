from app.apiv2 import *
from app.apiv2.jobs import _JobBase
from pyramid.httpexceptions import *
import shutil
import app.utils
import mimetypes

class _FilesBase(_JobBase):
    def uploadFile(self, id, fn, fh):
        id = int(id)
        filename = app.utils.results_filename(fn, id, mkdir=1)
        fout = file(filename, "w")
        shutil.copyfileobj(fh, fout)
        fout.close()
        

class FileGet(_FilesBase):
    REQTYPE="GET"
    HIDDEN=True
    PATH="/fileget/{file}"
    PRODUCES="application/octet-stream"

    def render(self):
        fn = self.request.matchdict["file"]
        if "." in fn:
            (job, filename) = fn.split(".", 1)
        else:
            job = fn
            filename = ""
        job = int(job)
        if filename in ("", "test"):
            ctype = "application/octet-stream"
            encoding = None
            downloadname = "%d.tar.bz2" % job
        else:
            (ctype, encoding) = mimetypes.guess_type(filename)
            if not ctype:
                ctype = "application/octet-stream"
            downloadname = filename

        try:
            localfilename = app.utils.results_filename(filename, job)
            self.request.response.body_file = file(localfilename, "r")
            self.request.response.content_type=ctype
            self.request.response.content_disposition = "attachment; filename=\"%s\"" % (downloadname)
            if encoding:
                self.request.response.content_encoding=encoding
            return self.request.response
        except Exception, e:
            if isinstance(e, IOError):
                return HTTPNotFound()
            else:
                raise

class UploadAttachment(_FilesBase):
    HIDDEN=True
    CONSUMES = "multipart/form-data"
    PATH = "/job/{id}/attachments"
    REQTYPE = "POST"
    SUMMARY = "Uploads an attachment to a job"
    OPERATION_ID='upload_job_attachment'
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to upload attachment to',
         'type': 'integer'},
        {'name': 'file',
         'in': 'formData',
         'required': True,
         'description': 'File to upload',
         'type': 'file'},
        {'name': 'filename',
         'in': 'formData',
         'required': False,
         'description': 'Filename on destination - defaults to local name'}]
    RESPONSES = { "200": {"description": "Successful response"}}

    def render(self):
        if self.request.POST.get("filename"):
            fn = self.request.POST['filename']
        else:
            fn = self.request.POST['file'].filename

        fh = self.request.POST['file'].file

        self.uploadFile(self.request.matchdict['id'], fn, fh)
        return {}

class UploadJobLog(_FilesBase):
    HIDDEN=True
    CONSUMES = "multipart/form-data"
    PATH = "/job/{id}/log"
    REQTYPE = "POST"
    SUMMARY = "Uploads a log tarball to a job"
    OPERATION_ID='upload_job_log'
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to upload log to',
         'type': 'integer'},
        {'name': 'file',
         'in': 'formData',
         'required': True,
         'description': 'File to upload',
         'type': 'file'}]
    RESPONSES = { "200": {"description": "Successful response"}}

    def render(self):
        fh = self.request.POST['file'].file
        self.uploadFile(self.request.matchdict['id'], "", fh)
        return {}

class UploadTestLog(_FilesBase):
    HIDDEN=True
    CONSUMES = "multipart/form-data"
    PATH = "/test/{id}/log"
    REQTYPE = "POST"
    SUMMARY = "Uploads a log tarball to a test"
    TAGS = ["jobs"]
    OPERATION_ID='upload_test_log'
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Test detail ID to upload log to',
         'type': 'integer'},
        {'name': 'file',
         'in': 'formData',
         'required': True,
         'description': 'File to upload',
         'type': 'file'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    
    def render(self):
        detailid = int(self.request.matchdict['id'])
        fh = self.request.POST['file'].file
        self.uploadFile(detailid, "test", fh)



RegisterAPI(UploadAttachment)
RegisterAPI(UploadJobLog)
RegisterAPI(UploadTestLog)
RegisterAPI(FileGet)
