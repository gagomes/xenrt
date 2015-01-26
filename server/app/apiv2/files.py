from app.apiv2 import *
from app.apiv2.jobs import _JobsBase
from pyramid.httpexceptions import *
import shutil
import app.utils
import mimetypes

class _FilesBase(_JobsBase):
    def uploadFile(self, id, fn, fh):
        id = int(id)
        filename = app.utils.results_filename(fn, id, mkdir=1)
        fout = file(filename, "w")
        shutil.copyfileobj(fh, fout)
        fout.close()
        
    def getDetailId(self, job, phase, test):
        job = self.getJobs(1, ids=[job], getResults=True)[job]
        return [x['detailid'] for x in job['results'].values() if x['phase'] == phase and x['test'] == test][0]

class _DownloadAttachment(_FilesBase):
    REQTYPE = "GET"
    PRODUCES="application/octet-stream"
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to get file from',
         'type': 'integer'},
        {'name': 'file',
         'in': 'path',
         'required': True,
         'description': 'File to download',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["jobs"]

    def render(self):
        job = int(self.request.matchdict['id'])
        details = self.getJobs(1, ids=[job], getParams=True)[job]['params']
        server = details[self.LOCATION_PARAM]
        if server != self.request.host:
            return HTTPFound(location="http://%s%s" % (server, self.request.path_qs))
        filename = self.request.matchdict["file"]
        (ctype, encoding) = mimetypes.guess_type(filename)
        if not ctype:
            ctype = "application/octet-stream"
        
        try:
            localfilename = app.utils.results_filename(filename, job)
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

class DownloadAttachmentPreRun(_DownloadAttachment):
    LOCATION_PARAM='JOB_FILES_SERVER'
    PATH='/job/{id}/attachment/prerun/{file}'
    DESCRIPTION='Download attachment from job, uploaded before job ran'
    OPERATION_ID='get_job_attachment_pre_run'

class DownloadAttachmentPostRun(_DownloadAttachment):
    LOCATION_PARAM='LOG_SERVER'
    PATH='/job/{id}/attachment/postrun/{file}'
    DESCRIPTION='Download attachment from job, uploaded after job ran'
    OPERATION_ID='get_job_attachment_post_run'

class UploadAttachment(_FilesBase):
    CONSUMES = "multipart/form-data"
    PATH = "/job/{id}/attachments"
    REQTYPE = "POST"
    DESCRIPTION = "Uploads an attachment to a job"
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
    DESCRIPTION = "Uploads a log tarball to a job"
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
        self.uploadFile(self.matchdict['jobid'], "", fh)
        return {}

class UploadTestLog(_FilesBase):
    CONSUMES = "multipart/form-data"
    PATH = "/job/{id}/log"
    REQTYPE = "POST"
    DESCRIPTION = "Uploads a log tarball to a job"
    TAGS = ["jobs"]
    OPERATION_ID='upload_test_log'
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to upload log to',
         'type': 'integer'},
        {'name': 'phase',
         'in': 'path',
         'required': True,
         'description': 'Job phase to upload log to',
         'type': 'integer'},
        {'name': 'test',
         'in': 'path',
         'required': True,
         'description': 'Job TC to upload log to',
         'type': 'integer'},
        {'name': 'file',
         'in': 'formData',
         'required': True,
         'description': 'File to upload',
         'type': 'file'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    
    def render(self):
        jobid = int(self.matchdict['jobid'])
        detailid = self.getDetailId(jobid, self.matchdict['phase'], self.matchdict['test'])
        fh = self.request.POST['file'].file
        self.uploadFile(detailid, "test", fh)

RegisterAPI(UploadAttachment)
RegisterAPI(DownloadAttachmentPreRun)
RegisterAPI(DownloadAttachmentPostRun)
RegisterAPI(UploadJobLog)
RegisterAPI(UploadTestLog)
