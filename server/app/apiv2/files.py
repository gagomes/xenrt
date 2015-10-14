from app.apiv2 import *
from app.apiv2.jobs import _JobBase
from pyramid.httpexceptions import *
import shutil
import app.utils
import os

class _FilesBase(_JobBase):
    REQUIRE_AUTH_IF_ENABLED = False
    FILEAPI=True
    def uploadFile(self, id, fn, fh):
        id = int(id)
        filename = app.utils.results_filename(fn, id, mkdir=1)
        fout = file(filename, "w")
        shutil.copyfileobj(fh, fout)
        fout.close()
        
    def parseGetURL(self):
        fn = self.request.matchdict["file"]
        if "." in fn:
            (job, filename) = fn.split(".", 1)
        else:
            job = fn
            filename = ""
        job = int(job)
        return (job, filename)


class IndexGet(_FilesBase):
    REQTYPE="GET"
    PATH="/index/{file}"
    PRODUCES="application/json"

    def render(self):
        (job, filename) = self.parseGetURL()
        localfilename = app.utils.results_filename(filename, job)

        index = app.utils.getTarIndex(localfilename, self.request.matchdict['file'])

        return index


class FileGet(_FilesBase):
    REQTYPE="GET"
    PATH="/fileget/{file}"
    PRODUCES="application/octet-stream"

    def render(self):
        (job, filename) = self.parseGetURL()
        if filename in ("", "test"):
            ctype = "application/octet-stream"
            encoding = None
            downloadname = "%d.tar.bz2" % job
        else:
            (ctype, encoding) = app.utils.getContentTypeAndEncoding(filename)
            if not ctype:
                ctype = "application/octet-stream"
            downloadname = filename

        try:
            localfilename = app.utils.results_filename(filename, job)
            f = file(localfilename, "r")
            self.request.response.body_file = f
            self.request.response.content_type=ctype
            self.request.response.content_disposition = "attachment; filename=\"%s\"" % (downloadname)
            self.request.response.content_length = os.fstat(f.fileno()).st_size
            if encoding:
                self.request.response.content_encoding=encoding
            return self.request.response
        except Exception, e:
            if isinstance(e, IOError):
                return HTTPNotFound()
            else:
                raise

class FileFromTar(_FilesBase):
    REQTYPE="GET"
    PATH="/log/{file}/*innerfile"
    PRODUCES="application/octet-stream"

    def getFD(self):
        (job, filename) = self.parseGetURL()
        localfilename = app.utils.results_filename(filename, job)
        innerfilename = "./%s" % "/".join(self.request.matchdict['innerfile'])
        size = None
        if os.path.exists("%s.index" % localfilename):
            f = open("%s.index" % localfilename)
            for l in f.readlines():
                ll = l.split()
                fname = " ".join(ll[5:len(ll)])
                _size = int(ll[2])
                if fname == innerfilename:
                    size = _size
                    break
            f.close()
        return (os.popen('tar -jxf %s -O "%s"' % (localfilename, innerfilename)), innerfilename, size)
    
    def render(self):
        (fd, fn, size) = self.getFD()
        
        self.request.response.body_file = fd
        
        (ctype, encoding) = app.utils.getContentTypeAndEncoding(fn)
        self.request.response.content_type = ctype
        if size:
            self.request.response.content_length=size

        return self.request.response


class UploadAttachment(_FilesBase):
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
    WRITE = True
    
    def render(self):
        detailid = int(self.request.matchdict['id'])
        fh = self.request.POST['file'].file
        self.uploadFile(detailid, "test", fh)
        db = self.getDB()
        cur = db.cursor()

        cur.execute("UPDATE tblResults SET uploaded = %s WHERE detailid = %s",
                    ["yes", detailid])

        db.commit()



RegisterAPI(UploadAttachment)
RegisterAPI(UploadJobLog)
RegisterAPI(UploadTestLog)
RegisterAPI(FileGet)
RegisterAPI(IndexGet)
RegisterAPI(FileFromTar)
