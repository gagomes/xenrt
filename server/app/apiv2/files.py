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

    def getServer(self, job, locationParam):
        job = int(job)
        return self.getJobs(1, ids=[job], getParams=True)[job]['params'][locationParam]
        

class FileGet(_FilesBase):
    REQTYPE="GET"
    HIDDEN=True
    PATH="/fileget/{file}"
    PRODUCES="application/octet-stream"

    def render(self):
        (job, filename) = self.request.matchdict["file"].split(".", 1)
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

class _GetAttachment(_FilesBase):
    REQTYPE = "GET"
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
        server = self.getServer(job, self.LOCATION_PARAM)

        return {'url': 'http://%s/xenrt/api/v2/fileget/%d.%s' % (server, job, self.request.matchdict['file'])}

class GetAttachmentPreRun(_GetAttachment):
    LOCATION_PARAM='JOB_FILES_SERVER'
    PATH='/job/{id}/attachment/prerun/{file}'
    DESCRIPTION='Get URL for job attachment, uploaded before job ran'
    OPERATION_ID='get_job_attachment_pre_run'

class GetAttachmentPostRun(_GetAttachment):
    LOCATION_PARAM='LOG_SERVER'
    PATH='/job/{id}/attachment/postrun/{file}'
    DESCRIPTION='Get URL for job attachment, uploaded after job ran'
    OPERATION_ID='get_job_attachment_post_run'

class GetJobLog(_FilesBase):
    PATH='/job/{id}/log'
    REQTYPE = "GET"
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to get file from',
         'type': 'integer'}]
    OPERATION_ID='get_job_log'
    DESCRIPTION = "Get URL for Job log"

    def render(self):
        job = int(self.request.matchdict['id'])
        server = self.getServer(job, "LOG_SERVER")
        return {'url': 'http://%s/xenrt/api/v2/fileget/%d.' % (server, job)}

class GetTestLogByName(_FilesBase):
    PATH='/job/{id}/{phase}/{test}/log'
    REQTYPE = "GET"
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Job ID to get file from',
         'type': 'integer'},
        {'name': 'phase',
         'in': 'path',
         'required': True,
         'description': 'Job ID to get file from',
         'type': 'string'},
        {'name': 'test',
         'in': 'path',
         'required': True,
         'description': 'Job ID to get file from',
         'type': 'string'}]
    OPERATION_ID='get_test_log_by_name'
    DESCRIPTION = "Get URL for Test log"

    def render(self):
        job = int(self.request.matchdict['id'])
        detailid = self.getDetailId(job, self.request.matchdict['phase'], self.request.matchdict['test'])
        server = self.getServer(job, "LOG_SERVER")
        return {'url': 'http://%s/xenrt/api/v2/fileget/%d.test' % (server, detailid)}

class GetTestLogById(_FilesBase):
    PATH='/test/{id}/log'
    REQTYPE = "GET"
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["jobs"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'Test detail ID to get file from',
         'type': 'integer'}]
    OPERATION_ID='get_test_log_by_id'
    DESCRIPTION = "Get URL for Test log"

    def render(self):
        detail = int(self.request.matchdict['id'])
        jobs = self.getJobs(1, detailids=[detail], getParams=True)
        if len(jobs.keys()) == 0:
            raise XenRTAPIError(HTTPNotFound, "Job not found")
        server = jobs.values()[0]['params']['LOG_SERVER']
        return {'url': 'http://%s/xenrt/api/v2/fileget/%d.test' % (server, detail)}

class UploadAttachment(_FilesBase):
    HIDDEN=True
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
    HIDDEN=True
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
        self.uploadFile(self.request.matchdict['jobid'], "", fh)
        return {}

class UploadTestLog(_FilesBase):
    HIDDEN=True
    CONSUMES = "multipart/form-data"
    PATH = "/test/{id}/log"
    REQTYPE = "POST"
    DESCRIPTION = "Uploads a log tarball to a test"
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
RegisterAPI(GetAttachmentPreRun)
RegisterAPI(GetAttachmentPostRun)
RegisterAPI(UploadJobLog)
RegisterAPI(UploadTestLog)
RegisterAPI(FileGet)
RegisterAPI(GetJobLog)
RegisterAPI(GetTestLogByName)
RegisterAPI(GetTestLogById)
